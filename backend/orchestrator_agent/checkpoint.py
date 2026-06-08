"""
Checkpointed multi-step workflows — checkpoint.py
=================================================

LangGraph-style durable execution for multi-step plans. A :class:`WorkflowRunner`
executes an ordered list of steps through the trust-aware pipeline and saves a
:class:`WorkflowState` checkpoint after **every** step. If the process crashes,
a step fails, or a step pauses for human approval, the run can be resumed from
the last checkpoint instead of starting over.

This is the synchronous analogue of LangGraph's ``interrupt()`` + persistent
checkpointer: state lives in the :class:`~orchestrator_agent.persistence.TrustStore`
keyed by ``thread_id``, so resume works across restarts.

A step is either a plain instruction string or ``{"input": ..., "intent": ...}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import logging
import uuid

from orchestrator_agent.models import Task

logger = logging.getLogger(__name__)

Step = Union[str, Dict[str, Any]]


@dataclass
class WorkflowState:
    thread_id: str
    steps: List[Step]
    step_index: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "running"      # running|awaiting_approval|completed|failed
    pending_approval_id: Optional[str] = None
    default_intent: str = "research"
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "steps": self.steps,
            "step_index": self.step_index,
            "results": self.results,
            "status": self.status,
            "pending_approval_id": self.pending_approval_id,
            "default_intent": self.default_intent,
            "updated_at": self.updated_at or datetime.utcnow().isoformat(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowState":
        return cls(
            thread_id=d["thread_id"],
            steps=d.get("steps", []),
            step_index=d.get("step_index", 0),
            results=d.get("results", []),
            status=d.get("status", "running"),
            pending_approval_id=d.get("pending_approval_id"),
            default_intent=d.get("default_intent", "research"),
            updated_at=d.get("updated_at", ""),
        )


class Checkpointer:
    """Persists and restores :class:`WorkflowState` via a TrustStore."""

    def __init__(self, store: Any):
        self.store = store

    async def save(self, state: WorkflowState) -> None:
        state.updated_at = datetime.utcnow().isoformat()
        await self.store.save_checkpoint(state.to_dict())

    async def load(self, thread_id: str) -> Optional[WorkflowState]:
        d = await self.store.load_checkpoint(thread_id)
        return WorkflowState.from_dict(d) if d else None

    async def delete(self, thread_id: str) -> None:
        await self.store.delete_checkpoint(thread_id)


class WorkflowRunner:
    """Runs and resumes checkpointed multi-step workflows."""

    def __init__(self, pipeline: Any, checkpointer: Checkpointer,
                 approval_manager: Any = None,
                 default_intent: str = "research"):
        self.pipeline = pipeline
        self.checkpointer = checkpointer
        self.approval_manager = approval_manager
        self.default_intent = default_intent

    async def run(self, steps: List[Step], context: Any, *,
                  thread_id: Optional[str] = None,
                  default_intent: Optional[str] = None) -> WorkflowState:
        state = WorkflowState(
            thread_id=thread_id or str(uuid.uuid4())[:12],
            steps=steps,
            default_intent=default_intent or self.default_intent,
        )
        await self.checkpointer.save(state)
        return await self._drive(state, context)

    async def resume(self, thread_id: str, context: Any) -> WorkflowState:
        state = await self.checkpointer.load(thread_id)
        if state is None:
            raise KeyError(f"No checkpoint for thread '{thread_id}'")
        if state.status == "completed":
            return state                          # terminal; nothing to do
        # A 'failed' workflow is resumable: re-run from the failed step.

        force_approve = False
        if (state.status == "awaiting_approval"
                and state.pending_approval_id and self.approval_manager):
            req = self.approval_manager.get(state.pending_approval_id)
            if req is None or req.is_pending:
                return state                      # still waiting on a human
            if req.is_approved:
                force_approve = True
            else:                                 # rejected / expired
                state.status = "failed"
                await self.checkpointer.save(state)
                return state

        state.status = "running"
        state.pending_approval_id = None
        return await self._drive(state, context, force_approve_first=force_approve)

    async def _drive(self, state: WorkflowState, context: Any,
                     force_approve_first: bool = False) -> WorkflowState:
        first = True
        while state.step_index < len(state.steps):
            step_input, intent = self._parse(state.steps[state.step_index],
                                             state.default_intent)
            task = Task(input_text=step_input, intent=intent)
            if force_approve_first and first:
                task.metadata["approved"] = True
            first = False

            result = await self.pipeline.execute_task(task, context)

            if result.error == "awaiting_approval":
                state.status = "awaiting_approval"
                state.pending_approval_id = result.metadata.get("approval_id")
                await self.checkpointer.save(state)
                return state

            state.results.append({
                "step": step_input,
                "intent": intent,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "cost_usd": round(result.cost, 6),
            })
            if not result.success:
                state.status = "failed"
                await self.checkpointer.save(state)
                return state

            state.step_index += 1
            await self.checkpointer.save(state)

        state.status = "completed"
        await self.checkpointer.save(state)
        return state

    @staticmethod
    def _parse(step: Step, default_intent: str):
        if isinstance(step, dict):
            return step.get("input", ""), step.get("intent", default_intent)
        return step, default_intent
