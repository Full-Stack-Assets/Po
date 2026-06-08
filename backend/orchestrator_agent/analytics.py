"""
Analytics & Metrics — analytics.py
Dashboard-ready aggregations: time-series, cost breakdown, provider stats.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class TimeSeriesPoint:
    timestamp: str
    value: float
    label: Optional[str] = None


@dataclass
class CostBreakdown:
    provider: str
    model: str
    cost_usd: float
    token_count: int
    run_count: int


@dataclass
class ProviderMetrics:
    provider: str
    total_requests: int
    success_count: int
    failure_count: int
    avg_latency_ms: float
    total_cost_usd: float
    circuit_open: bool


@dataclass
class DashboardMetrics:
    total_runs: int
    total_cost_usd: float
    total_tokens: int
    success_rate: float
    avg_latency_ms: float
    active_providers: int
    pending_approvals: int
    cost_trend: List[TimeSeriesPoint] = field(default_factory=list)
    runs_trend: List[TimeSeriesPoint] = field(default_factory=list)
    cost_by_provider: List[CostBreakdown] = field(default_factory=list)
    cost_by_intent: List[CostBreakdown] = field(default_factory=list)
    provider_metrics: List[ProviderMetrics] = field(default_factory=list)
    top_intents: List[Tuple[str, int]] = field(default_factory=list)


def metrics_to_dict(metrics: DashboardMetrics) -> dict:
    raw = asdict(metrics)
    raw["top_intents"] = [list(t) for t in metrics.top_intents]
    return raw


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _bucket_key(dt: datetime, bucket: str) -> str:
    if bucket == "day":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


class AnalyticsEngine:
    def __init__(
        self,
        trust_store: Any,
        llm_manager: Any,
        approval_manager: Any = None,
    ) -> None:
        self._store = trust_store
        self._llm = llm_manager
        self._approvals = approval_manager

    async def _filtered_runs(self, period_hours: int) -> List[Dict[str, Any]]:
        runs = await self._store.list_runs(limit=10_000)
        if not period_hours:
            return runs
        cutoff = datetime.now(timezone.utc) - timedelta(hours=period_hours)
        filtered: List[Dict[str, Any]] = []
        for r in runs:
            ts = _parse_ts(r.get("created_at"))
            if ts is not None and ts >= cutoff:
                filtered.append(r)
        return filtered

    async def get_dashboard(self, period_hours: int = 24) -> DashboardMetrics:
        runs = await self._filtered_runs(period_hours)

        total_runs = len(runs)
        successes = sum(1 for r in runs if r.get("success"))
        total_cost = sum(float(r.get("cost_usd") or 0) for r in runs)
        total_tokens = sum(int(r.get("tokens_used") or 0) for r in runs)
        latencies = [float(r["latency_ms"]) for r in runs if r.get("latency_ms") is not None]
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        success_rate = round(successes / total_runs, 4) if total_runs else 0.0

        health = self._llm.get_health() if self._llm else []
        active_providers = sum(1 for h in health if not h.get("circuit_open", False))

        pending = 0
        if self._approvals is not None:
            try:
                pending_list = self._approvals.list_pending()
                pending = len(pending_list)
            except Exception:
                pending = 0

        cost_trend = await self.get_cost_timeseries(period_hours)
        runs_trend = await self.get_runs_timeseries(period_hours)
        cost_by_provider = await self.get_cost_by_provider(period_hours)
        cost_by_intent = await self.get_cost_by_intent(period_hours)
        provider_metrics = await self.get_provider_leaderboard()

        intent_counts: Dict[str, int] = defaultdict(int)
        for r in runs:
            intent = r.get("intent") or "unknown"
            intent_counts[intent] += 1
        top_intents = sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return DashboardMetrics(
            total_runs=total_runs,
            total_cost_usd=round(total_cost, 6),
            total_tokens=total_tokens,
            success_rate=success_rate,
            avg_latency_ms=avg_latency,
            active_providers=active_providers,
            pending_approvals=pending,
            cost_trend=cost_trend,
            runs_trend=runs_trend,
            cost_by_provider=cost_by_provider,
            cost_by_intent=cost_by_intent,
            provider_metrics=provider_metrics,
            top_intents=top_intents,
        )

    async def get_cost_timeseries(
        self, period_hours: int = 24, bucket: str = "hour"
    ) -> List[TimeSeriesPoint]:
        runs = await self._filtered_runs(period_hours)
        buckets: Dict[str, float] = defaultdict(float)
        for r in runs:
            ts = _parse_ts(r.get("created_at"))
            if ts is None:
                continue
            key = _bucket_key(ts, bucket)
            buckets[key] += float(r.get("cost_usd") or 0)
        return [
            TimeSeriesPoint(timestamp=k, value=round(v, 6), label="cost_usd")
            for k, v in sorted(buckets.items())
        ]

    async def get_runs_timeseries(
        self, period_hours: int = 24, bucket: str = "hour"
    ) -> List[TimeSeriesPoint]:
        runs = await self._filtered_runs(period_hours)
        buckets: Dict[str, int] = defaultdict(int)
        for r in runs:
            ts = _parse_ts(r.get("created_at"))
            if ts is None:
                continue
            key = _bucket_key(ts, bucket)
            buckets[key] += 1
        return [
            TimeSeriesPoint(timestamp=k, value=float(v), label="runs")
            for k, v in sorted(buckets.items())
        ]

    async def get_cost_by_provider(self, period_hours: int = 24) -> List[CostBreakdown]:
        runs = await self._filtered_runs(period_hours)
        agg: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "count": 0}
        )
        for r in runs:
            provider = r.get("provider_used") or "unknown"
            model = r.get("model_used") or "unknown"
            entry = agg[(provider, model)]
            entry["cost"] += float(r.get("cost_usd") or 0)
            entry["tokens"] += int(r.get("tokens_used") or 0)
            entry["count"] += 1
        return sorted(
            [
                CostBreakdown(
                    provider=k[0],
                    model=k[1],
                    cost_usd=round(v["cost"], 6),
                    token_count=v["tokens"],
                    run_count=v["count"],
                )
                for k, v in agg.items()
            ],
            key=lambda c: c.cost_usd,
            reverse=True,
        )

    async def get_cost_by_intent(self, period_hours: int = 24) -> List[CostBreakdown]:
        runs = await self._filtered_runs(period_hours)
        agg: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "count": 0}
        )
        for r in runs:
            intent = r.get("intent") or "unknown"
            entry = agg[intent]
            entry["cost"] += float(r.get("cost_usd") or 0)
            entry["tokens"] += int(r.get("tokens_used") or 0)
            entry["count"] += 1
        return sorted(
            [
                CostBreakdown(
                    provider=intent,
                    model="*",
                    cost_usd=round(v["cost"], 6),
                    token_count=v["tokens"],
                    run_count=v["count"],
                )
                for intent, v in agg.items()
            ],
            key=lambda c: c.cost_usd,
            reverse=True,
        )

    async def get_provider_leaderboard(self) -> List[ProviderMetrics]:
        health_list = self._llm.get_health() if self._llm else []
        runs = await self._store.list_runs(limit=10_000)

        cost_by_provider: Dict[str, float] = defaultdict(float)
        for r in runs:
            provider = r.get("provider_used") or "unknown"
            cost_by_provider[provider] += float(r.get("cost_usd") or 0)

        results: List[ProviderMetrics] = []
        for h in health_list:
            provider = h.get("provider", "unknown")
            total = h.get("total_requests", 0)
            sr_raw = h.get("success_rate", "0%")
            if isinstance(sr_raw, str):
                sr_raw = sr_raw.replace("%", "").replace(",", "")
                try:
                    sr = float(sr_raw) / 100.0
                except (ValueError, TypeError):
                    sr = 0.0
            else:
                sr = float(sr_raw)
            success_count = int(round(sr * total))
            failure_count = total - success_count
            results.append(
                ProviderMetrics(
                    provider=provider,
                    total_requests=total,
                    success_count=success_count,
                    failure_count=failure_count,
                    avg_latency_ms=float(h.get("avg_latency_ms", 0)),
                    total_cost_usd=round(cost_by_provider.get(provider, 0.0), 6),
                    circuit_open=bool(h.get("circuit_open", False)),
                )
            )
        return sorted(results, key=lambda p: p.total_requests, reverse=True)

    async def get_usage_summary(self, user_id: Optional[str] = None) -> dict:
        runs = await self._store.list_runs(limit=10_000)
        if user_id:
            runs = [r for r in runs if r.get("user_id") == user_id]

        total_runs = len(runs)
        successes = sum(1 for r in runs if r.get("success"))
        total_cost = sum(float(r.get("cost_usd") or 0) for r in runs)
        total_tokens = sum(int(r.get("tokens_used") or 0) for r in runs)

        llm_usage = self._llm.get_usage() if self._llm else {}

        return {
            "total_runs": total_runs,
            "success_count": successes,
            "failure_count": total_runs - successes,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "success_rate": round(successes / total_runs, 4) if total_runs else 0.0,
            "llm_usage": llm_usage,
        }
