"""
Workflow Scheduler — scheduler.py
=================================

Cron-like scheduler that runs workflows on a recurring basis and
generates verified status reports. Supports:

- Recurring workflows with cron-style scheduling
- Morning digest reports (overnight results + metrics)
- One-shot delayed execution
- Pause/resume of scheduled tasks

Uses ``asyncio`` for the event loop — no external scheduler dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ScheduleEntry:
    schedule_id: str
    name: str
    workflow_goal: str
    interval_seconds: int
    enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0
    last_result: Optional[Dict[str, Any]] = None
    max_runs: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "workflow_goal": self.workflow_goal,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "last_result_status": (self.last_result or {}).get("status"),
            "max_runs": self.max_runs,
            "created_at": self.created_at,
        }


@dataclass
class DigestReport:
    """A morning digest summarizing overnight activity."""
    generated_at: str
    period_hours: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    total_cost_usd: float
    verified_actions: int
    failed_verifications: int
    highlights: List[str]
    scheduled_runs: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "period_hours": self.period_hours,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "verified_actions": self.verified_actions,
            "failed_verifications": self.failed_verifications,
            "highlights": self.highlights,
            "scheduled_runs": self.scheduled_runs,
        }

    def summary_text(self) -> str:
        lines = [
            f"Po Digest — {self.generated_at[:10]}",
            f"Period: last {self.period_hours}h",
            f"Runs: {self.successful_runs}/{self.total_runs} succeeded",
            f"Cost: ${self.total_cost_usd:.4f}",
            f"Verified: {self.verified_actions} actions, "
            f"{self.failed_verifications} failed",
        ]
        if self.highlights:
            lines.append("Highlights:")
            for h in self.highlights:
                lines.append(f"  • {h}")
        return "\n".join(lines)


class WorkflowScheduler:
    """Async scheduler that runs workflows on intervals."""

    def __init__(self, orchestrator: Any):
        self._orch = orchestrator
        self._schedules: Dict[str, ScheduleEntry] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._on_complete: Optional[Callable] = None

    def on_complete(self, callback: Callable) -> "WorkflowScheduler":
        self._on_complete = callback
        return self

    def schedule(
        self,
        name: str,
        goal: str,
        interval_seconds: int = 3600,
        max_runs: Optional[int] = None,
    ) -> ScheduleEntry:
        entry = ScheduleEntry(
            schedule_id=str(uuid.uuid4())[:12],
            name=name,
            workflow_goal=goal,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            next_run=(datetime.utcnow()
                      + timedelta(seconds=interval_seconds)).isoformat(),
        )
        self._schedules[entry.schedule_id] = entry
        if self._running:
            self._tasks[entry.schedule_id] = asyncio.create_task(
                self._run_loop(entry))
        return entry

    def schedule_once(self, name: str, goal: str,
                      delay_seconds: int = 0) -> ScheduleEntry:
        return self.schedule(name, goal,
                             interval_seconds=max(delay_seconds, 1),
                             max_runs=1)

    def cancel(self, schedule_id: str) -> bool:
        entry = self._schedules.get(schedule_id)
        if not entry:
            return False
        entry.enabled = False
        task = self._tasks.pop(schedule_id, None)
        if task:
            task.cancel()
        return True

    def pause(self, schedule_id: str) -> bool:
        entry = self._schedules.get(schedule_id)
        if not entry:
            return False
        entry.enabled = False
        return True

    def resume(self, schedule_id: str) -> bool:
        entry = self._schedules.get(schedule_id)
        if not entry:
            return False
        entry.enabled = True
        if self._running and schedule_id not in self._tasks:
            self._tasks[schedule_id] = asyncio.create_task(
                self._run_loop(entry))
        return True

    def list_schedules(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._schedules.values()]

    def get(self, schedule_id: str) -> Optional[ScheduleEntry]:
        return self._schedules.get(schedule_id)

    async def start(self) -> None:
        self._running = True
        for sid, entry in self._schedules.items():
            if entry.enabled and sid not in self._tasks:
                self._tasks[sid] = asyncio.create_task(
                    self._run_loop(entry))
        logger.info(f"Scheduler started with {len(self._tasks)} entries")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(),
                                 return_exceptions=True)
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def _run_loop(self, entry: ScheduleEntry) -> None:
        try:
            while entry.enabled and self._running:
                if entry.max_runs and entry.run_count >= entry.max_runs:
                    entry.enabled = False
                    break

                await asyncio.sleep(entry.interval_seconds)
                if not entry.enabled or not self._running:
                    break

                logger.info(f"Scheduler: running '{entry.name}'")
                entry.last_run = datetime.utcnow().isoformat()
                entry.run_count += 1

                try:
                    result = await self._orch.plan_and_run_workflow(
                        entry.workflow_goal)
                    entry.last_result = result
                    entry.next_run = (
                        datetime.utcnow()
                        + timedelta(seconds=entry.interval_seconds)
                    ).isoformat()
                    if self._on_complete:
                        try:
                            await self._on_complete(entry, result)
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Scheduled workflow '{entry.name}' "
                                 f"failed: {e}")
                    entry.last_result = {"status": "error",
                                         "error": str(e)}
        except asyncio.CancelledError:
            pass

    async def generate_digest(
        self, period_hours: int = 24,
    ) -> DigestReport:
        runs = await self._orch.list_runs(limit=200)
        cutoff = (datetime.utcnow()
                  - timedelta(hours=period_hours)).isoformat()

        period_runs = [r for r in runs
                       if r.get("created_at", r.get("task_id", "")) >= cutoff]

        successful = sum(1 for r in period_runs if r.get("success"))
        failed = len(period_runs) - successful
        total_cost = sum(r.get("cost_usd", 0) for r in period_runs)

        verified = sum(
            1 for r in period_runs
            if (r.get("verification") or {}).get("all_passed"))
        failed_verifications = sum(
            1 for r in period_runs
            if (r.get("verification") and
                not (r.get("verification") or {}).get("all_passed")))

        highlights = []
        if failed > 0:
            highlights.append(f"{failed} workflow(s) failed — review needed")
        if failed_verifications > 0:
            highlights.append(
                f"{failed_verifications} verification(s) failed — "
                f"actions may not have completed")
        refunded = sum(1 for r in period_runs if r.get("refunded"))
        if refunded:
            highlights.append(f"{refunded} action(s) auto-refunded")
        if successful and not highlights:
            highlights.append("All workflows completed and verified")

        scheduled_runs = []
        for entry in self._schedules.values():
            if entry.last_run and entry.last_run >= cutoff:
                scheduled_runs.append({
                    "name": entry.name,
                    "status": (entry.last_result or {}).get("status",
                                                            "unknown"),
                    "run_count": entry.run_count,
                })

        return DigestReport(
            generated_at=datetime.utcnow().isoformat(),
            period_hours=period_hours,
            total_runs=len(period_runs),
            successful_runs=successful,
            failed_runs=failed,
            total_cost_usd=total_cost,
            verified_actions=verified,
            failed_verifications=failed_verifications,
            highlights=highlights,
            scheduled_runs=scheduled_runs,
        )

    async def run_immediate(self, schedule_id: str) -> Dict[str, Any]:
        entry = self._schedules.get(schedule_id)
        if not entry:
            return {"error": f"No schedule '{schedule_id}'"}
        entry.last_run = datetime.utcnow().isoformat()
        entry.run_count += 1
        result = await self._orch.plan_and_run_workflow(entry.workflow_goal)
        entry.last_result = result
        return result
