"""
Trust-layer persistence — persistence.py
========================================

Durable storage for the records the reliability story depends on: approval
requests, orchestration runs, and validation results. Two interchangeable
backends sit behind one :class:`TrustStore` interface:

- :class:`InMemoryTrustStore` — the default; zero-dependency, used in tests and
  when no database is configured.
- :class:`PostgresTrustStore` — asyncpg-backed; creates its schema on ``init``
  and powers cross-restart durability and the ``/v2/stats`` reliability metrics.

Use :func:`create_trust_store` to pick a backend from config/env. The
orchestrator writes through to the store but never depends on it being present,
so the system degrades to purely in-memory behaviour if persistence is off.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import json
import logging
import os

logger = logging.getLogger(__name__)


class TrustStore(ABC):
    async def init(self) -> None: ...

    @abstractmethod
    async def upsert_approval(self, approval: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def list_pending_approvals(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def record_run(self, run: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def record_validation(self, validation: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def stats(self) -> Dict[str, Any]: ...

    async def close(self) -> None: ...


def _rate(numer: int, denom: int) -> float:
    return round(numer / denom, 4) if denom else 0.0


# ── In-memory backend ──────────────────────────────────────────────────

class InMemoryTrustStore(TrustStore):
    def __init__(self) -> None:
        self._approvals: Dict[str, Dict[str, Any]] = {}
        self._runs: List[Dict[str, Any]] = []
        self._validations: List[Dict[str, Any]] = []

    async def upsert_approval(self, approval: Dict[str, Any]) -> None:
        self._approvals[approval["approval_id"]] = dict(approval)

    async def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        return self._approvals.get(approval_id)

    async def list_pending_approvals(self) -> List[Dict[str, Any]]:
        return [a for a in self._approvals.values()
                if a.get("status") == "pending"]

    async def record_run(self, run: Dict[str, Any]) -> None:
        # Replace any prior record for the same task_id (resume updates).
        self._runs = [r for r in self._runs
                      if r.get("task_id") != run.get("task_id")]
        self._runs.append(dict(run))

    async def record_validation(self, validation: Dict[str, Any]) -> None:
        self._validations.append(dict(validation))

    async def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self._runs))[:limit]

    async def stats(self) -> Dict[str, Any]:
        runs = self._runs
        total = len(runs)
        successful = sum(1 for r in runs if r.get("success"))
        verified = [r for r in runs if r.get("verification")]
        verified_pass = sum(1 for r in verified
                            if (r.get("verification") or {}).get("all_passed"))
        refunded = sum(1 for r in runs if r.get("refunded"))
        pending = len([a for a in self._approvals.values()
                       if a.get("status") == "pending"])
        return {
            "total_runs": total,
            "successful_runs": successful,
            "success_rate": _rate(successful, total),
            "verified_runs": len(verified),
            "verified_pass": verified_pass,
            "verified_pass_rate": _rate(verified_pass, len(verified)),
            "refunded_runs": refunded,
            "refund_rate": _rate(refunded, total),
            "validations_recorded": len(self._validations),
            "approvals_total": len(self._approvals),
            "approvals_pending": pending,
        }


# ── Postgres backend ───────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    approval_id    text PRIMARY KEY,
    type           text,
    summary        text,
    status         text,
    payload        jsonb,
    edited_payload jsonb,
    created_at     timestamptz,
    expires_at     timestamptz,
    decided_at     timestamptz
);
CREATE TABLE IF NOT EXISTS runs (
    task_id          text PRIMARY KEY,
    conversation_id  text,
    intent           text,
    status           text,
    input            text,
    output           text,
    success          boolean,
    error            text,
    tokens_used      integer,
    cost_usd         double precision,
    provider         text,
    model            text,
    validation_score text,
    verification     jsonb,
    refunded         boolean DEFAULT false,
    created_at       timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS validations (
    id               text PRIMARY KEY,
    task_id          text,
    idea             text,
    overall_score    integer,
    score            text,
    demand_score     integer,
    competitor_score integer,
    icp_score        integer,
    wtp_score        integer,
    backend          text,
    created_at       timestamptz DEFAULT now()
);
"""


class PostgresTrustStore(TrustStore):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: Any = None

    async def init(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(self.dsn)
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA)
        logger.info("PostgresTrustStore initialized")

    async def upsert_approval(self, a: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO approvals (approval_id, type, summary, status,
                       payload, edited_payload, created_at, expires_at,
                       decided_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9)
                   ON CONFLICT (approval_id) DO UPDATE SET
                       status=$4, edited_payload=$6::jsonb, decided_at=$9""",
                a["approval_id"], a.get("type"), a.get("summary"),
                a.get("status"), json.dumps(a.get("payload")),
                json.dumps(a.get("edited_payload")),
                _dt(a.get("created_at")), _dt(a.get("expires_at")),
                _dt(a.get("decided_at")),
            )

    async def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approvals WHERE approval_id=$1", approval_id)
        return _approval_row(row) if row else None

    async def list_pending_approvals(self) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM approvals WHERE status='pending'")
        return [_approval_row(r) for r in rows]

    async def record_run(self, r: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO runs (task_id, conversation_id, intent, status,
                       input, output, success, error, tokens_used, cost_usd,
                       provider, model, validation_score, verification,
                       refunded)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,
                       $14::jsonb,$15)
                   ON CONFLICT (task_id) DO UPDATE SET
                       status=$4, output=$6, success=$7, error=$8,
                       tokens_used=$9, cost_usd=$10, provider=$11, model=$12,
                       validation_score=$13, verification=$14::jsonb,
                       refunded=$15""",
                r["task_id"], r.get("conversation_id"), r.get("intent"),
                r.get("status"), r.get("input"), r.get("output"),
                r.get("success"), r.get("error"), r.get("tokens_used"),
                r.get("cost_usd"), r.get("provider"), r.get("model"),
                r.get("validation_score"),
                json.dumps(r.get("verification")), r.get("refunded", False),
            )

    async def record_validation(self, v: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO validations (id, task_id, idea, overall_score,
                       score, demand_score, competitor_score, icp_score,
                       wtp_score, backend)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                   ON CONFLICT (id) DO NOTHING""",
                v["id"], v.get("task_id"), v.get("idea"),
                v.get("overall_score"), v.get("score"),
                v.get("demand_score"), v.get("competitor_score"),
                v.get("icp_score"), v.get("wtp_score"), v.get("backend"),
            )

    async def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(r) for r in rows]

    async def stats(self) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                  count(*) AS total,
                  count(*) FILTER (WHERE success) AS successful,
                  count(*) FILTER (WHERE verification IS NOT NULL) AS verified,
                  count(*) FILTER (WHERE
                      (verification->>'all_passed')::boolean) AS verified_pass,
                  count(*) FILTER (WHERE refunded) AS refunded
                FROM runs""")
            vcount = await conn.fetchval("SELECT count(*) FROM validations")
            atotal = await conn.fetchval("SELECT count(*) FROM approvals")
            apend = await conn.fetchval(
                "SELECT count(*) FROM approvals WHERE status='pending'")
        total = row["total"] or 0
        verified = row["verified"] or 0
        return {
            "total_runs": total,
            "successful_runs": row["successful"] or 0,
            "success_rate": _rate(row["successful"] or 0, total),
            "verified_runs": verified,
            "verified_pass": row["verified_pass"] or 0,
            "verified_pass_rate": _rate(row["verified_pass"] or 0, verified),
            "refunded_runs": row["refunded"] or 0,
            "refund_rate": _rate(row["refunded"] or 0, total),
            "validations_recorded": vcount or 0,
            "approvals_total": atotal or 0,
            "approvals_pending": apend or 0,
        }

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


def _dt(value: Any):
    from datetime import datetime
    if not value:
        return None
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _approval_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    for k in ("payload", "edited_payload"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    for k in ("created_at", "expires_at", "decided_at"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = d[k].isoformat()
    return d


def create_trust_store(config: Optional[Dict[str, Any]] = None) -> TrustStore:
    """Pick a backend from config/env.

    Postgres is used when a DSN is provided via ``config['dsn']`` or the
    ``DATABASE_URL`` env var *and* asyncpg is importable; otherwise the
    in-memory store is returned.
    """
    config = config or {}
    if config.get("backend") == "memory":
        return InMemoryTrustStore()
    dsn = config.get("dsn") or os.environ.get("DATABASE_URL")
    if dsn:
        try:
            import asyncpg  # noqa: F401
            return PostgresTrustStore(dsn)
        except ImportError:
            logger.warning("asyncpg not installed; using in-memory store")
    return InMemoryTrustStore()
