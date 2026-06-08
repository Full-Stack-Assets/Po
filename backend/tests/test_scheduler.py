"""Tests for the workflow scheduler (scheduler.py)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from orchestrator_agent.scheduler import (
    WorkflowScheduler, ScheduleEntry, DigestReport,
)


# ── Helpers ──────────────────────────────────────────────────────────

def make_mock_orch():
    orch = MagicMock()
    orch.plan_and_run_workflow = AsyncMock(return_value={
        "status": "completed",
        "results": [{"success": True, "cost_usd": 0.001}],
    })
    orch.list_runs = AsyncMock(return_value=[
        {"success": True, "cost_usd": 0.001, "intent": "research",
         "verification": {"all_passed": True}, "refunded": False,
         "created_at": "2099-01-01T00:00:00"},
        {"success": False, "cost_usd": 0.002, "intent": "write",
         "verification": None, "refunded": False,
         "created_at": "2099-01-01T00:00:00"},
    ])
    return orch


# ── ScheduleEntry ────────────────────────────────────────────────────

def test_schedule_entry_to_dict():
    entry = ScheduleEntry(
        schedule_id="s1", name="test", workflow_goal="do stuff",
        interval_seconds=3600)
    d = entry.to_dict()
    assert d["schedule_id"] == "s1"
    assert d["name"] == "test"
    assert d["interval_seconds"] == 3600
    assert d["enabled"] is True
    assert d["run_count"] == 0


# ── DigestReport ─────────────────────────────────────────────────────

def test_digest_report_to_dict():
    report = DigestReport(
        generated_at="2025-01-01T08:00:00",
        period_hours=24,
        total_runs=10,
        successful_runs=8,
        failed_runs=2,
        total_cost_usd=0.05,
        verified_actions=7,
        failed_verifications=1,
        highlights=["2 failed", "1 verification failed"],
        scheduled_runs=[],
    )
    d = report.to_dict()
    assert d["total_runs"] == 10
    assert d["successful_runs"] == 8
    assert d["total_cost_usd"] == 0.05
    assert len(d["highlights"]) == 2


def test_digest_summary_text():
    report = DigestReport(
        generated_at="2025-01-01T08:00:00",
        period_hours=24, total_runs=5, successful_runs=5,
        failed_runs=0, total_cost_usd=0.01,
        verified_actions=5, failed_verifications=0,
        highlights=["All workflows completed and verified"],
        scheduled_runs=[],
    )
    text = report.summary_text()
    assert "5/5 succeeded" in text
    assert "$0.0100" in text
    assert "All workflows completed" in text


# ── WorkflowScheduler ───────────────────────────────────────────────

def test_schedule_creates_entry():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule("daily research", "Research AI trends",
                           interval_seconds=86400)
    assert entry.name == "daily research"
    assert entry.workflow_goal == "Research AI trends"
    assert entry.interval_seconds == 86400
    assert entry.enabled is True
    assert len(sched.list_schedules()) == 1


def test_schedule_once():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule_once("one-shot", "Do a thing", delay_seconds=60)
    assert entry.max_runs == 1
    assert entry.interval_seconds == 60


def test_cancel_schedule():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule("test", "goal", interval_seconds=60)
    assert sched.cancel(entry.schedule_id)
    assert not entry.enabled
    assert not sched.cancel("nonexistent")


def test_pause_resume_schedule():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule("test", "goal", interval_seconds=60)
    assert sched.pause(entry.schedule_id)
    assert not entry.enabled
    assert sched.resume(entry.schedule_id)
    assert entry.enabled


def test_list_schedules():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    sched.schedule("a", "goal a", interval_seconds=60)
    sched.schedule("b", "goal b", interval_seconds=120)
    items = sched.list_schedules()
    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"a", "b"}


@pytest.mark.asyncio
async def test_run_immediate():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule("test", "Research topic", interval_seconds=3600)
    result = await sched.run_immediate(entry.schedule_id)
    assert result["status"] == "completed"
    assert entry.run_count == 1
    orch.plan_and_run_workflow.assert_called_once_with("Research topic")


@pytest.mark.asyncio
async def test_run_immediate_unknown():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    result = await sched.run_immediate("nonexistent")
    assert "error" in result


@pytest.mark.asyncio
async def test_generate_digest():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    report = await sched.generate_digest(period_hours=24)
    assert report.total_runs == 2
    assert report.successful_runs == 1
    assert report.failed_runs == 1
    assert report.verified_actions == 1
    assert len(report.highlights) >= 1


@pytest.mark.asyncio
async def test_generate_digest_all_success():
    orch = make_mock_orch()
    orch.list_runs = AsyncMock(return_value=[
        {"success": True, "cost_usd": 0.001, "intent": "research",
         "verification": {"all_passed": True}, "refunded": False,
         "created_at": "2099-01-01T00:00:00"},
    ])
    sched = WorkflowScheduler(orch)
    report = await sched.generate_digest(24)
    assert report.failed_runs == 0
    assert any("completed" in h.lower() for h in report.highlights)


def test_on_complete_callback():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    called = []
    sched.on_complete(lambda entry, result: called.append(entry.name))
    assert sched._on_complete is not None


def test_get_schedule():
    orch = make_mock_orch()
    sched = WorkflowScheduler(orch)
    entry = sched.schedule("test", "goal", interval_seconds=60)
    found = sched.get(entry.schedule_id)
    assert found is entry
    assert sched.get("nonexistent") is None
