"""Integration tests for the trust layer wired into ExecutionPipeline."""

import pytest

from orchestrator_agent.models import (
    Task, TaskContext, TaskStatus, AgentResult, AgentProfile, Constraint,
)
from orchestrator_agent.orchestrator import ExecutionPipeline, ConstraintEngine
from orchestrator_agent.validation import ValidationGate
from orchestrator_agent.verification import VerificationLayer
from orchestrator_agent.approvals import ApprovalManager


# ── Stubs ──────────────────────────────────────────────────────────────

class StubAgent:
    def __init__(self, output="done", agent_id="stub", cost=0.5, tokens=100):
        self.agent_id = agent_id
        self._output = output
        self._cost = cost
        self._tokens = tokens

    async def execute(self, task, context):
        return AgentResult(
            agent_id=self.agent_id, task_id=task.task_id,
            output=self._output, success=True,
            tokens_used=self._tokens, cost=self._cost,
            model_used="stub-model", provider_used="stub",
        )


class StubRegistry:
    def __init__(self, agent):
        self._profile = AgentProfile(agent_id=agent.agent_id, name="Stub",
                                     max_concurrent=5)

    def get_profile(self, agent_id):
        return self._profile


class StubRouter:
    def __init__(self, agent):
        self._agent = agent
        self.registry = StubRegistry(agent)

    def route(self, task):
        return self._agent


def make_pipeline(agent, **trust):
    engine = ConstraintEngine()
    engine.add_constraint(Constraint("token_budget", 100_000, unit="tokens"))
    engine.add_constraint(Constraint("cost_budget", 10.0, unit="USD"))
    return ExecutionPipeline(StubRouter(agent), engine, **trust), engine


# ── Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validation_blocks_red_idea():
    pipeline, _ = make_pipeline(StubAgent(),
                                validation_gate=ValidationGate())
    task = Task(input_text="", intent="research",
                metadata={"require_validation": True})
    result = await pipeline.execute_task(task, TaskContext())
    assert result.success is False
    assert task.status == TaskStatus.FAILED
    assert "Validation failed" in result.error


@pytest.mark.asyncio
async def test_validation_override_allows_execution():
    pipeline, _ = make_pipeline(StubAgent(),
                                validation_gate=ValidationGate())
    task = Task(input_text="", intent="research",
                metadata={"require_validation": True,
                          "validation_override": True})
    result = await pipeline.execute_task(task, TaskContext())
    assert result.success is True
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_approval_gate_pauses_then_resumes():
    agent = StubAgent(output="email sent")
    mgr = ApprovalManager(auto_approve=False)
    pipeline, _ = make_pipeline(agent, approval_manager=mgr)

    task = Task(input_text="send cold outreach", intent="write")
    ctx = TaskContext()
    paused = await pipeline.execute_task(task, ctx)

    assert paused.success is False
    assert paused.error == "awaiting_approval"
    assert task.status == TaskStatus.AWAITING_APPROVAL
    approval_id = paused.metadata["approval_id"]
    assert len(mgr.list_pending()) == 1

    resumed = await pipeline.resume_task(approval_id, ctx, approved=True)
    assert resumed.success is True
    assert resumed.output == "email sent"
    assert mgr.list_pending() == []


@pytest.mark.asyncio
async def test_approval_rejection_cancels_task():
    agent = StubAgent()
    mgr = ApprovalManager(auto_approve=False)
    pipeline, _ = make_pipeline(agent, approval_manager=mgr)
    task = Task(input_text="ship it", intent="code")
    ctx = TaskContext()
    paused = await pipeline.execute_task(task, ctx)
    resumed = await pipeline.resume_task(
        paused.metadata["approval_id"], ctx, approved=False)
    assert resumed.success is False
    assert resumed.error == "approval_rejected"
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_resume_reconstructs_task_after_restart():
    # Process 1: task pauses for approval.
    mgr = ApprovalManager(auto_approve=False)
    p1, _ = make_pipeline(StubAgent(), approval_manager=mgr)
    task = Task(input_text="send outreach", intent="write")
    paused = await p1.execute_task(task, TaskContext())
    approval_id = paused.metadata["approval_id"]

    # Process 2 ("restart"): brand-new pipeline with empty task cache, same
    # (hydrated) approval manager. Resume must rebuild the task from payload.
    p2, _ = make_pipeline(StubAgent(output="sent"), approval_manager=mgr)
    assert p2._tasks == {}
    resumed = await p2.resume_task(approval_id, TaskContext(), approved=True)
    assert resumed.success is True
    assert resumed.output == "sent"


@pytest.mark.asyncio
async def test_auto_approve_does_not_pause():
    mgr = ApprovalManager(auto_approve=True)
    pipeline, _ = make_pipeline(StubAgent(), approval_manager=mgr)
    task = Task(input_text="write a post", intent="write")
    result = await pipeline.execute_task(task, TaskContext())
    assert result.success is True
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_verification_records_summary():
    async def fetcher(url):
        return 200

    agent = StubAgent(output="deployed at https://example.com")
    layer = VerificationLayer(fetcher=fetcher)
    pipeline, _ = make_pipeline(agent, verification_layer=layer)
    result = await pipeline.execute_task(
        Task(input_text="deploy", intent="code"), TaskContext())
    assert result.success is True
    assert result.metadata["verification"]["all_passed"] is True


@pytest.mark.asyncio
async def test_pipeline_verifies_declared_action_specs():
    from orchestrator_agent.verifiers import HttpDeployVerifier

    async def fetch(url):
        return 200, "live"

    layer = VerificationLayer()
    layer.register(HttpDeployVerifier(fetch))
    pipeline, _ = make_pipeline(StubAgent(output="shipped"),
                                verification_layer=layer)
    task = Task(input_text="deploy", intent="code",
                metadata={"verify_actions": [
                    {"type": "deploy_health", "url": "https://po.app"}]})
    result = await pipeline.execute_task(task, TaskContext())
    assert result.metadata["verification"]["all_passed"] is True
    assert result.metadata["verification"]["checked"] == 1


@pytest.mark.asyncio
async def test_verification_failure_refunds_budget():
    async def fetcher(url):
        return 500

    agent = StubAgent(output="deployed at https://example.com/broken",
                      cost=0.5, tokens=100)
    layer = VerificationLayer(fetcher=fetcher, fail_on_unverified=True)
    pipeline, engine = make_pipeline(agent, verification_layer=layer)
    result = await pipeline.execute_task(
        Task(input_text="deploy", intent="code"), TaskContext())

    assert result.success is False
    assert result.error == "verification_failed"
    assert result.metadata["refunded"] is True
    # Budget was consumed then refunded -> net zero.
    status = {c["name"]: c for c in engine.get_status()}
    assert status["cost_budget"]["used"] == 0.0
    assert status["token_budget"]["used"] == 0.0
