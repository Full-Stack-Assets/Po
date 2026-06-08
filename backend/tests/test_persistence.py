"""Unit tests for trust-layer persistence (in-memory backend).

The Postgres backend is exercised only when a real ``DATABASE_URL`` is exported
(see ``test_postgres_*``); otherwise those tests are skipped so the suite runs
without a database.
"""

import os

import pytest

from orchestrator_agent.persistence import (
    InMemoryTrustStore, create_trust_store, PostgresTrustStore,
)

_DSN = os.environ.get("DATABASE_URL")
requires_pg = pytest.mark.skipif(not _DSN, reason="DATABASE_URL not set")
from orchestrator_agent.approvals import (
    ApprovalManager, ApprovalRequest, ApprovalType, ApprovalDecision,
)


@pytest.mark.asyncio
async def test_approval_roundtrip_and_pending_filter():
    store = InMemoryTrustStore()
    req = ApprovalRequest(type=ApprovalType.OUTREACH, summary="cold email",
                          payload={"input": "send it"})
    await store.upsert_approval(req.to_dict())
    assert (await store.get_approval(req.approval_id))["summary"] == "cold email"
    assert len(await store.list_pending_approvals()) == 1

    req.status = ApprovalDecision.APPROVED
    await store.upsert_approval(req.to_dict())
    assert await store.list_pending_approvals() == []


@pytest.mark.asyncio
async def test_record_run_is_idempotent_on_task_id():
    store = InMemoryTrustStore()
    await store.record_run({"task_id": "t1", "success": False})
    await store.record_run({"task_id": "t1", "success": True})  # resume update
    runs = await store.list_runs()
    assert len(runs) == 1
    assert runs[0]["success"] is True


@pytest.mark.asyncio
async def test_stats_aggregates_runs():
    store = InMemoryTrustStore()
    await store.record_run({"task_id": "a", "success": True,
                            "verification": {"all_passed": True}})
    await store.record_run({"task_id": "b", "success": False,
                            "verification": {"all_passed": False},
                            "refunded": True})
    await store.record_run({"task_id": "c", "success": True})
    await store.record_validation({"id": "v1", "task_id": "a"})

    stats = await store.stats()
    assert stats["total_runs"] == 3
    assert stats["successful_runs"] == 2
    assert stats["success_rate"] == round(2 / 3, 4)
    assert stats["verified_runs"] == 2
    assert stats["verified_pass"] == 1
    assert stats["refunded_runs"] == 1
    assert stats["validations_recorded"] == 1


@pytest.mark.asyncio
async def test_approval_hydration_restores_pending_queue():
    store = InMemoryTrustStore()
    req = ApprovalRequest(type=ApprovalType.DEPLOY, summary="ship",
                          payload={"input": "deploy", "intent": "code",
                                   "task_id": "t9"})
    await store.upsert_approval(req.to_dict())

    # Simulate a fresh process: new manager, hydrate from store.
    mgr = ApprovalManager(auto_approve=False)
    pending = await store.list_pending_approvals()
    mgr.load([ApprovalRequest.from_dict(d) for d in pending])
    assert len(mgr.list_pending()) == 1
    restored = mgr.get(req.approval_id)
    assert restored.type == ApprovalType.DEPLOY
    assert restored.payload["intent"] == "code"


def test_create_trust_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(create_trust_store(), InMemoryTrustStore)
    assert isinstance(create_trust_store({"backend": "memory"}),
                      InMemoryTrustStore)


def test_create_trust_store_uses_postgres_when_dsn_present():
    store = create_trust_store({"dsn": "postgresql://localhost/po"})
    # asyncpg is a declared dependency, so a DSN selects the Postgres backend.
    assert isinstance(store, PostgresTrustStore)


@requires_pg
@pytest.mark.asyncio
async def test_postgres_roundtrip_runs_and_stats():
    store = PostgresTrustStore(_DSN)
    await store.init()
    try:
        await store.record_run({"task_id": "pg-test-1", "intent": "code",
                                "status": "completed", "success": True,
                                "verification": {"all_passed": True}})
        runs = await store.list_runs(5)
        assert any(r["task_id"] == "pg-test-1" for r in runs)
        stats = await store.stats()
        assert stats["total_runs"] >= 1
    finally:
        await store.close()


@requires_pg
@pytest.mark.asyncio
async def test_postgres_checkpoint_roundtrip():
    store = PostgresTrustStore(_DSN)
    await store.init()
    try:
        await store.save_checkpoint({
            "thread_id": "pg-wf", "step_index": 2, "status": "running",
            "steps": ["a", "b", "c"], "results": [{"step": "a"}],
        })
        loaded = await store.load_checkpoint("pg-wf")
        assert loaded["step_index"] == 2
        assert loaded["steps"] == ["a", "b", "c"]
        assert any(c["thread_id"] == "pg-wf"
                   for c in await store.list_checkpoints())
        await store.delete_checkpoint("pg-wf")
        assert await store.load_checkpoint("pg-wf") is None
    finally:
        await store.close()
