"""Unit tests for analytics & metrics module."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator_agent.analytics import (
    AnalyticsEngine,
    DashboardMetrics,
    metrics_to_dict,
)


def _make_run(
    intent="summarize",
    success=True,
    cost_usd=0.01,
    tokens_used=100,
    latency_ms=200,
    provider_used="openai",
    model_used="gpt-4",
    created_at=None,
):
    return {
        "intent": intent,
        "success": success,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "provider_used": provider_used,
        "model_used": model_used,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }


def _build_engine(runs=None, health=None, pending=None):
    trust_store = MagicMock()
    trust_store.list_runs = AsyncMock(return_value=runs or [])

    llm_manager = MagicMock()
    llm_manager.get_health = MagicMock(return_value=health or [])
    llm_manager.get_usage = MagicMock(return_value={})

    approval_manager = MagicMock()
    approval_manager.list_pending = MagicMock(return_value=pending or [])

    return AnalyticsEngine(trust_store, llm_manager, approval_manager)


# ── Dashboard ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_dashboard():
    engine = _build_engine(runs=[])
    dashboard = await engine.get_dashboard(period_hours=24)
    assert dashboard.total_runs == 0
    assert dashboard.total_cost_usd == 0.0
    assert dashboard.total_tokens == 0
    assert dashboard.success_rate == 0.0
    assert dashboard.avg_latency_ms == 0.0


@pytest.mark.asyncio
async def test_dashboard_with_runs():
    runs = [
        _make_run(cost_usd=0.05, tokens_used=500, latency_ms=100, success=True),
        _make_run(cost_usd=0.10, tokens_used=1000, latency_ms=300, success=True),
        _make_run(cost_usd=0.02, tokens_used=200, latency_ms=150, success=False),
    ]
    engine = _build_engine(runs=runs)
    dashboard = await engine.get_dashboard(period_hours=24)
    assert dashboard.total_runs == 3
    assert abs(dashboard.total_cost_usd - 0.17) < 1e-4
    assert dashboard.total_tokens == 1700
    assert abs(dashboard.success_rate - round(2 / 3, 4)) < 1e-4
    expected_latency = round((100 + 300 + 150) / 3, 2)
    assert abs(dashboard.avg_latency_ms - expected_latency) < 0.1


# ── Cost breakdown ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_by_provider():
    runs = [
        _make_run(provider_used="openai", model_used="gpt-4", cost_usd=0.10),
        _make_run(provider_used="openai", model_used="gpt-4", cost_usd=0.05),
        _make_run(provider_used="anthropic", model_used="claude-3", cost_usd=0.20),
    ]
    engine = _build_engine(runs=runs)
    breakdown = await engine.get_cost_by_provider(period_hours=24)
    # Sorted by cost descending
    assert breakdown[0].provider == "anthropic"
    assert breakdown[0].cost_usd == 0.2
    assert breakdown[0].run_count == 1
    assert breakdown[1].provider == "openai"
    assert abs(breakdown[1].cost_usd - 0.15) < 1e-6
    assert breakdown[1].run_count == 2


@pytest.mark.asyncio
async def test_cost_by_intent():
    runs = [
        _make_run(intent="summarize", cost_usd=0.03),
        _make_run(intent="summarize", cost_usd=0.04),
        _make_run(intent="code", cost_usd=0.10),
    ]
    engine = _build_engine(runs=runs)
    by_intent = await engine.get_cost_by_intent(period_hours=24)
    assert by_intent[0].provider == "code"  # provider field holds intent name
    assert by_intent[0].cost_usd == 0.1
    assert by_intent[1].provider == "summarize"
    assert abs(by_intent[1].cost_usd - 0.07) < 1e-6


# ── Serialization ────────────────────────────────────────────────────


def test_metrics_to_dict():
    m = DashboardMetrics(
        total_runs=5,
        total_cost_usd=0.5,
        total_tokens=5000,
        success_rate=0.8,
        avg_latency_ms=150.0,
        active_providers=2,
        pending_approvals=1,
        top_intents=[("summarize", 3), ("code", 2)],
    )
    d = metrics_to_dict(m)
    # Should be JSON-serializable
    serialized = json.dumps(d)
    assert '"total_runs": 5' in serialized
    # top_intents should be lists, not tuples
    assert d["top_intents"] == [["summarize", 3], ["code", 2]]


# ── Provider leaderboard ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_leaderboard():
    runs = [
        _make_run(provider_used="openai", cost_usd=0.05),
        _make_run(provider_used="anthropic", cost_usd=0.10),
    ]
    health = [
        {
            "provider": "openai",
            "total_requests": 100,
            "success_rate": "95%",
            "avg_latency_ms": 120,
            "circuit_open": False,
        },
        {
            "provider": "anthropic",
            "total_requests": 50,
            "success_rate": "90%",
            "avg_latency_ms": 200,
            "circuit_open": False,
        },
    ]
    engine = _build_engine(runs=runs, health=health)
    leaderboard = await engine.get_provider_leaderboard()
    # Sorted by total_requests descending
    assert leaderboard[0].provider == "openai"
    assert leaderboard[0].total_requests == 100
    assert leaderboard[0].success_count == 95
    assert leaderboard[0].failure_count == 5
    assert abs(leaderboard[0].total_cost_usd - 0.05) < 1e-6
    assert leaderboard[1].provider == "anthropic"
    assert leaderboard[1].total_requests == 50
