"""Tests for checkpointed multi-step workflows."""

import pytest

from orchestrator_agent.models import (
    TaskContext, AgentResult, AgentProfile, Constraint,
)
from orchestrator_agent.orchestrator import ExecutionPipeline, ConstraintEngine
from orchestrator_agent.approvals import ApprovalManager, ApprovalDecision
from orchestrator_agent.persistence import InMemoryTrustStore
from orchestrator_agent.checkpoint import (
    Checkpointer, WorkflowRunner, WorkflowState,
)


# ── Stubs ──────────────────────────────────────────────────────────────

class StubAgent:
    def __init__(self, agent_id="stub"):
        self.agent_id = agent_id

    async def execute(self, task, context):
        return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                           output="ok:" + task.input_text, success=True,
                           tokens_used=10, cost=0.1)


class FailingOnceAgent:
    """Fails only on its very first call, succeeds on every call after."""
    def __init__(self):
        self.agent_id = "flaky"
        self._calls = 0

    async def execute(self, task, context):
        self._calls += 1
        if self._calls == 1:
            return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                               output="", success=False, error="boom")
        return AgentResult(agent_id=self.agent_id, task_id=task.task_id,
                           output="ok:" + task.input_text, success=True)


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


def make(agent, **trust):
    engine = ConstraintEngine()
    engine.add_constraint(Constraint("token_budget", 100_000, unit="tokens"))
    engine.add_constraint(Constraint("cost_budget", 10.0, unit="USD"))
    pipeline = ExecutionPipeline(StubRouter(agent), engine, **trust)
    store = InMemoryTrustStore()
    runner = WorkflowRunner(pipeline, Checkpointer(store),
                            approval_manager=trust.get("approval_manager"))
    return runner, store


# ── Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_workflow_completes_and_checkpoints_each_step():
    runner, store = make(StubAgent())
    state = await runner.run(["step one", "step two", "step three"],
                             TaskContext(), thread_id="wf1")
    assert state.status == "completed"
    assert state.step_index == 3
    assert len(state.results) == 3
    # Final checkpoint persisted.
    saved = await store.load_checkpoint("wf1")
    assert saved["status"] == "completed"


@pytest.mark.asyncio
async def test_resume_continues_from_persisted_checkpoint():
    # Persist a half-finished workflow (as if the process crashed at step 1).
    runner, store = make(StubAgent())
    partial = WorkflowState(thread_id="wf2",
                            steps=["a", "b", "c"], step_index=1,
                            results=[{"step": "a", "success": True}])
    await store.save_checkpoint(partial.to_dict())

    state = await runner.resume("wf2", TaskContext())
    assert state.status == "completed"
    assert state.step_index == 3
    # Only the remaining two steps ran (one pre-existing result + 2 new).
    assert len(state.results) == 3


@pytest.mark.asyncio
async def test_failed_step_pauses_and_resume_retries():
    agent = FailingOnceAgent()
    runner, store = make(agent)
    state = await runner.run(["x", "y"], TaskContext(), thread_id="wf3")
    assert state.status == "failed"
    assert state.step_index == 0  # failed on first step, not advanced

    # Resume re-runs the failed step; the flaky agent now succeeds.
    resumed = await runner.resume("wf3", TaskContext())
    assert resumed.status == "completed"
    assert resumed.step_index == 2


@pytest.mark.asyncio
async def test_workflow_pauses_for_approval_then_resumes():
    mgr = ApprovalManager(auto_approve=False)
    runner, store = make(StubAgent(), approval_manager=mgr)
    # Second step is a 'write' intent -> needs approval.
    steps = [{"input": "research market", "intent": "research"},
             {"input": "send outreach", "intent": "write"},
             {"input": "summarize", "intent": "summarize"}]
    state = await runner.run(steps, TaskContext(), thread_id="wf4")
    assert state.status == "awaiting_approval"
    assert state.step_index == 1
    assert state.pending_approval_id is not None

    # Approve, then resume -> the approved step runs and the workflow finishes.
    mgr.decide(state.pending_approval_id, ApprovalDecision.APPROVED)
    resumed = await runner.resume("wf4", TaskContext())
    assert resumed.status == "completed"
    assert resumed.step_index == 3
    assert len(resumed.results) == 3


@pytest.mark.asyncio
async def test_resume_blocked_while_approval_pending():
    mgr = ApprovalManager(auto_approve=False)
    runner, _ = make(StubAgent(), approval_manager=mgr)
    state = await runner.run([{"input": "ship", "intent": "code"}],
                             TaskContext(), thread_id="wf5")
    assert state.status == "awaiting_approval"
    # No decision yet -> resume returns the still-pending state, unchanged.
    again = await runner.resume("wf5", TaskContext())
    assert again.status == "awaiting_approval"


@pytest.mark.asyncio
async def test_rejected_approval_fails_workflow_on_resume():
    mgr = ApprovalManager(auto_approve=False)
    runner, _ = make(StubAgent(), approval_manager=mgr)
    state = await runner.run([{"input": "ship", "intent": "code"}],
                             TaskContext(), thread_id="wf6")
    mgr.decide(state.pending_approval_id, ApprovalDecision.REJECTED)
    resumed = await runner.resume("wf6", TaskContext())
    assert resumed.status == "failed"


@pytest.mark.asyncio
async def test_checkpointer_roundtrip_and_delete():
    store = InMemoryTrustStore()
    cp = Checkpointer(store)
    state = WorkflowState(thread_id="t", steps=["a"], step_index=1)
    await cp.save(state)
    loaded = await cp.load("t")
    assert loaded.step_index == 1
    assert (await cp.load("t")).updated_at  # timestamp set on save
    await cp.delete("t")
    assert await cp.load("t") is None
