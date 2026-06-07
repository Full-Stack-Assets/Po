"""Tests for auto-generated workflow steps from the PlannerAgent."""

import json
import pytest

from orchestrator_agent.models import (
    Task, TaskContext, AgentResult, AgentProfile, Constraint,
)
from orchestrator_agent.orchestrator import (
    ExecutionPipeline, ConstraintEngine, OrchestratorAgent,
)
from orchestrator_agent.approvals import ApprovalManager
from orchestrator_agent.persistence import InMemoryTrustStore
from orchestrator_agent.checkpoint import Checkpointer, WorkflowRunner


# ── Stubs ─────────────────────────────────────────────────────────────

class StubExecutor:
    """Executes any task successfully with a canned output."""
    def __init__(self):
        self.agent_id = "executor"

    async def execute(self, task, context):
        return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                           output=f"done:{task.input_text}", success=True,
                           tokens_used=10, cost=0.01)


class StubPlanner:
    """Returns a canned JSON plan from a goal."""
    def __init__(self, plan_json: str):
        self.agent_id = "planner"
        self._plan = plan_json

    async def execute(self, task, context):
        return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                           output=self._plan, success=True,
                           tokens_used=50, cost=0.02)


class FailingPlanner:
    def __init__(self):
        self.agent_id = "planner"

    async def execute(self, task, context):
        return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                           output="", success=False, error="LLM down")


class StubRouter:
    def __init__(self, agent):
        self._agent = agent

        class _Reg:
            def get_profile(_self, _id):
                return AgentProfile(agent_id=agent.agent_id, name="Stub",
                                    max_concurrent=5)
        self.registry = _Reg()

    def route(self, task):
        return self._agent


# ── _parse_plan unit tests ───────────────────────────────────────────

class TestParsePlan:
    def test_standard_json_array(self):
        raw = json.dumps([
            {"description": "Research competitors", "agent_type": "research"},
            {"description": "Draft outreach", "agent_type": "write"},
            {"description": "Build landing page", "agent_type": "code"},
        ])
        steps = OrchestratorAgent._parse_plan(raw)
        assert len(steps) == 3
        assert steps[0] == {"input": "Research competitors", "intent": "research"}
        assert steps[1] == {"input": "Draft outreach", "intent": "write"}
        assert steps[2] == {"input": "Build landing page", "intent": "code"}

    def test_markdown_fenced_json(self):
        raw = "Here's the plan:\n```json\n" + json.dumps([
            {"description": "Analyze data", "agent_type": "analysis"},
        ]) + "\n```\nLet me know!"
        steps = OrchestratorAgent._parse_plan(raw)
        assert len(steps) == 1
        assert steps[0]["intent"] == "analyze"

    def test_plain_string_items(self):
        raw = json.dumps(["step one", "step two"])
        steps = OrchestratorAgent._parse_plan(raw)
        assert len(steps) == 2
        assert steps[0] == {"input": "step one", "intent": "research"}

    def test_empty_output_returns_empty(self):
        assert OrchestratorAgent._parse_plan("") == []
        assert OrchestratorAgent._parse_plan("no json here") == []

    def test_invalid_json_returns_empty(self):
        assert OrchestratorAgent._parse_plan("[not valid json}") == []

    def test_alternate_field_names(self):
        raw = json.dumps([
            {"task": "Summarize report", "type": "summarize"},
            {"input": "Deploy service", "intent": "code"},
        ])
        steps = OrchestratorAgent._parse_plan(raw)
        assert steps[0] == {"input": "Summarize report", "intent": "summarize"}
        assert steps[1] == {"input": "Deploy service", "intent": "code"}

    def test_skips_items_without_description(self):
        raw = json.dumps([
            {"agent_type": "research"},
            {"description": "Valid step", "agent_type": "write"},
            42,
        ])
        steps = OrchestratorAgent._parse_plan(raw)
        assert len(steps) == 1
        assert steps[0]["input"] == "Valid step"


# ── Integration tests ────────────────────────────────────────────────

def _make_runner(executor):
    engine = ConstraintEngine()
    engine.add_constraint(Constraint("token_budget", 100_000, unit="tokens"))
    engine.add_constraint(Constraint("cost_budget", 10.0, unit="USD"))
    pipeline = ExecutionPipeline(StubRouter(executor), engine)
    store = InMemoryTrustStore()
    runner = WorkflowRunner(pipeline, Checkpointer(store))
    return runner, store


@pytest.mark.asyncio
async def test_plan_then_run_workflow():
    """A planner produces steps; the runner executes them in order."""
    plan = json.dumps([
        {"description": "Research the ICP", "agent_type": "research"},
        {"description": "Draft cold email", "agent_type": "write"},
        {"description": "Summarize results", "agent_type": "summarize"},
    ])
    planner = StubPlanner(plan)
    executor = StubExecutor()
    runner, store = _make_runner(executor)

    # Simulate what plan_and_run_workflow does.
    plan_task = Task(input_text="grow my SaaS", intent="plan")
    plan_result = await planner.execute(plan_task, TaskContext())
    steps = OrchestratorAgent._parse_plan(plan_result.output)
    state = await runner.run(steps, TaskContext(), thread_id="pw1")

    assert state.status == "completed"
    assert state.step_index == 3
    assert len(state.results) == 3
    assert state.results[0]["intent"] == "research"
    assert state.results[1]["intent"] == "write"
    assert state.results[2]["intent"] == "summarize"


@pytest.mark.asyncio
async def test_plan_with_approval_gate():
    """A 'write' step in a plan pauses for approval."""
    plan = json.dumps([
        {"description": "Research market", "agent_type": "research"},
        {"description": "Send outreach", "agent_type": "write"},
    ])
    executor = StubExecutor()
    mgr = ApprovalManager(auto_approve=False)
    engine = ConstraintEngine()
    engine.add_constraint(Constraint("token_budget", 100_000, unit="tokens"))
    engine.add_constraint(Constraint("cost_budget", 10.0, unit="USD"))
    pipeline = ExecutionPipeline(StubRouter(executor), engine,
                                 approval_manager=mgr)
    store = InMemoryTrustStore()
    runner = WorkflowRunner(pipeline, Checkpointer(store),
                            approval_manager=mgr)

    steps = OrchestratorAgent._parse_plan(plan)
    state = await runner.run(steps, TaskContext(), thread_id="pw2")
    assert state.status == "awaiting_approval"
    assert state.step_index == 1


@pytest.mark.asyncio
async def test_failing_planner_returns_error():
    planner = FailingPlanner()
    plan_task = Task(input_text="goal", intent="plan")
    result = await planner.execute(plan_task, TaskContext())
    assert not result.success
    assert result.error == "LLM down"


@pytest.mark.asyncio
async def test_planner_returning_no_steps():
    planner = StubPlanner("I can't decompose that.")
    plan_task = Task(input_text="vague", intent="plan")
    result = await planner.execute(plan_task, TaskContext())
    steps = OrchestratorAgent._parse_plan(result.output)
    assert steps == []
