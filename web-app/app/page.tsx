"use client";

import { useEffect, useState, useCallback } from "react";
import { api, isApiError } from "@/lib/api";
import type { AnalyticsDashboard, StatusResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Activity,
  CheckCircle2,
  DollarSign,
  Zap,
  Clock,
  Server,
  RefreshCw,
} from "lucide-react";

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<AnalyticsDashboard | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setRefreshing(true);
      const [d, s] = await Promise.all([
        api.getAnalyticsDashboard(24),
        api.getStatus(),
      ]);
      if (isApiError(d) || isApiError(s)) {
        const err = [d, s].find(isApiError);
        setError(err?.error || "API error");
        return;
      }
      setDashboard(d);
      setStatus(s);
      setError("");
    } catch (e: any) {
      setError(e.message || "Failed to connect to backend");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20">
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-6 py-4 text-sm text-red-400">
          {error}
        </div>
        <p className="text-xs text-zinc-500">
          Make sure the backend is running at{" "}
          {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
        </p>
      </div>
    );
  }

  if (!dashboard || !status) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-zinc-800" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-64 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-64 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-lg bg-zinc-900" />
      </div>
    );
  }

  const successPct = Math.round((dashboard.success_rate ?? 0) * 100);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-zinc-500">
            Last 24 hours &middot; auto-refreshing every 5s
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="flex items-center gap-2 rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KPICard
          title="Total Runs"
          value={dashboard.total_runs.toLocaleString()}
          icon={<Activity size={18} />}
          color="violet"
        />
        <KPICard
          title="Success Rate"
          value={`${successPct}%`}
          icon={<CheckCircle2 size={18} />}
          color={successPct >= 90 ? "green" : successPct >= 70 ? "yellow" : "red"}
        />
        <KPICard
          title="Total Cost"
          value={`$${dashboard.total_cost_usd.toFixed(4)}`}
          icon={<DollarSign size={18} />}
          color="blue"
        />
        <KPICard
          title="Total Tokens"
          value={dashboard.total_tokens.toLocaleString()}
          icon={<Zap size={18} />}
          color="yellow"
        />
        <KPICard
          title="Avg Latency"
          value={`${Math.round(dashboard.avg_latency_ms)}ms`}
          icon={<Clock size={18} />}
          color={dashboard.avg_latency_ms < 2000 ? "green" : dashboard.avg_latency_ms < 5000 ? "yellow" : "red"}
        />
        <KPICard
          title="Active Providers"
          value={dashboard.active_providers.toString()}
          icon={<Server size={18} />}
          color="violet"
        />
      </div>

      {/* Pending Approvals Banner */}
      {dashboard.pending_approvals > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-yellow-800/50 bg-yellow-950/30 px-4 py-3">
          <div className="h-2 w-2 rounded-full bg-yellow-400 animate-pulse" />
          <span className="text-sm text-yellow-300">
            {dashboard.pending_approvals} pending approval{dashboard.pending_approvals !== 1 ? "s" : ""} require attention
          </span>
        </div>
      )}

      {/* Trend Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <TrendChart
          title="Cost Trend (24h)"
          data={dashboard.cost_trend}
          formatValue={(v) => `$${v.toFixed(4)}`}
          color="blue"
        />
        <TrendChart
          title="Runs Trend (24h)"
          data={dashboard.runs_trend}
          formatValue={(v) => v.toString()}
          color="violet"
        />
      </div>

      {/* Cost by Provider & Top Intents */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-zinc-400">
              Cost by Provider
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dashboard.cost_by_provider.length === 0 ? (
              <p className="text-sm text-zinc-600">No provider data yet</p>
            ) : (
              <div className="space-y-3">
                {dashboard.cost_by_provider.map((p, i) => {
                  const maxCost = Math.max(...dashboard.cost_by_provider.map((x) => x.cost_usd));
                  const pct = maxCost > 0 ? (p.cost_usd / maxCost) * 100 : 0;
                  return (
                    <div key={i} className="space-y-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium text-zinc-300">{p.provider}</span>
                        <span className="text-zinc-500">
                          ${p.cost_usd.toFixed(4)} &middot; {p.run_count} runs
                        </span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-zinc-800">
                        <div
                          className="h-2 rounded-full bg-blue-500 transition-all duration-500"
                          style={{ width: `${Math.max(pct, 2)}%` }}
                        />
                      </div>
                      <p className="text-xs text-zinc-600">
                        {p.model} &middot; {p.token_count.toLocaleString()} tokens
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-zinc-400">
              Top Intents
            </CardTitle>
          </CardHeader>
          <CardContent>
            {dashboard.top_intents.length === 0 ? (
              <p className="text-sm text-zinc-600">No intent data yet</p>
            ) : (
              <div className="space-y-2">
                {dashboard.top_intents.map(([name, count], i) => {
                  const maxCount = dashboard.top_intents[0]?.[1] ?? 1;
                  const pct = (count / maxCount) * 100;
                  return (
                    <div key={i} className="group relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-zinc-800/50">
                      <span className="w-6 text-right text-xs font-mono text-zinc-600">
                        {i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="truncate text-sm font-medium text-zinc-300">
                            {name}
                          </span>
                          <Badge variant="secondary" className="ml-2 tabular-nums">
                            {count}
                          </Badge>
                        </div>
                        <div className="mt-1 h-1 w-full rounded-full bg-zinc-800">
                          <div
                            className="h-1 rounded-full bg-violet-500/60 transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Provider Health Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-zinc-400">
            Provider Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          {dashboard.provider_metrics.length === 0 ? (
            <p className="text-sm text-zinc-600">No provider metrics available</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                    <th className="pb-3 pr-4 font-medium">Provider</th>
                    <th className="pb-3 pr-4 font-medium">Status</th>
                    <th className="pb-3 pr-4 font-medium text-right">Requests</th>
                    <th className="pb-3 pr-4 font-medium text-right">Success Rate</th>
                    <th className="pb-3 pr-4 font-medium text-right">Avg Latency</th>
                    <th className="pb-3 font-medium text-right">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.provider_metrics.map((pm) => {
                    const sr = pm.total_requests > 0
                      ? Math.round((pm.success_count / pm.total_requests) * 100)
                      : 0;
                    return (
                      <tr
                        key={pm.provider}
                        className="border-b border-zinc-800/50 transition-colors hover:bg-zinc-800/30"
                      >
                        <td className="py-3 pr-4 font-medium text-zinc-200">
                          {pm.provider}
                        </td>
                        <td className="py-3 pr-4">
                          <Badge variant={pm.circuit_open ? "destructive" : "default"}>
                            {pm.circuit_open ? "Circuit Open" : "Healthy"}
                          </Badge>
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums text-zinc-300">
                          {pm.total_requests.toLocaleString()}
                        </td>
                        <td className="py-3 pr-4 text-right">
                          <span
                            className={`tabular-nums ${
                              sr >= 95
                                ? "text-green-400"
                                : sr >= 80
                                  ? "text-yellow-400"
                                  : "text-red-400"
                            }`}
                          >
                            {sr}%
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums text-zinc-300">
                          {Math.round(pm.avg_latency_ms)}ms
                        </td>
                        <td className="py-3 text-right tabular-nums text-zinc-300">
                          ${pm.total_cost_usd.toFixed(4)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Constraint Gauges */}
      {status.constraints.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-zinc-400">
              Constraint Budgets
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {status.constraints.map((c) => {
                const pct = c.max > 0 ? Math.min((c.used / c.max) * 100, 100) : 0;
                const isHigh = pct >= 80;
                const isCritical = pct >= 95;
                return (
                  <div key={c.name} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-zinc-300">{c.name}</span>
                      <span
                        className={`text-xs font-mono ${
                          isCritical
                            ? "text-red-400"
                            : isHigh
                              ? "text-yellow-400"
                              : "text-zinc-500"
                        }`}
                      >
                        {Math.round(pct)}%
                      </span>
                    </div>
                    <Progress value={pct} />
                    <div className="flex items-baseline justify-between text-xs text-zinc-500">
                      <span>
                        {c.unit === "USD" ? `$${c.used.toFixed(4)}` : c.used.toLocaleString()}
                      </span>
                      <span>
                        {c.unit === "USD" ? `$${c.max.toFixed(2)}` : c.max.toLocaleString()} {c.unit !== "USD" ? c.unit : ""}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ---- Sub-components ---- */

function KPICard({
  title,
  value,
  icon,
  color,
}: {
  title: string;
  value: string;
  icon: React.ReactNode;
  color: "violet" | "green" | "yellow" | "red" | "blue";
}) {
  const colors = {
    violet: "text-violet-400",
    green: "text-green-400",
    yellow: "text-yellow-400",
    red: "text-red-400",
    blue: "text-blue-400",
  };

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-zinc-500">{title}</p>
            <p className={`mt-1 text-2xl font-bold tabular-nums ${colors[color]}`}>
              {value}
            </p>
          </div>
          <div className={`rounded-lg bg-zinc-800 p-2 ${colors[color]}`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function TrendChart({
  title,
  data,
  formatValue,
  color,
}: {
  title: string;
  data: Array<{ timestamp: string; value: number; label?: string }>;
  formatValue: (v: number) => string;
  color: "blue" | "violet";
}) {
  const maxVal = Math.max(...data.map((d) => d.value), 1);
  const barColor = color === "blue" ? "bg-blue-500" : "bg-violet-500";
  const barHoverColor = color === "blue" ? "hover:bg-blue-400" : "hover:bg-violet-400";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-zinc-400">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="text-sm text-zinc-600">No data for this period</p>
        ) : (
          <div className="flex items-end gap-[2px]" style={{ height: 160 }}>
            {data.map((d, i) => {
              const heightPct = maxVal > 0 ? (d.value / maxVal) * 100 : 0;
              const label = d.label || new Date(d.timestamp).getHours().toString().padStart(2, "0") + ":00";
              return (
                <div
                  key={i}
                  className="group relative flex-1 min-w-0 flex flex-col items-center justify-end"
                  style={{ height: "100%" }}
                >
                  {/* Tooltip */}
                  <div className="pointer-events-none absolute -top-8 z-10 hidden rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200 shadow-lg group-hover:block whitespace-nowrap">
                    {formatValue(d.value)}
                  </div>
                  <div
                    className={`w-full rounded-t ${barColor} ${barHoverColor} transition-all duration-300 cursor-default`}
                    style={{ height: `${Math.max(heightPct, 2)}%`, minHeight: 2 }}
                  />
                </div>
              );
            })}
          </div>
        )}
        {data.length > 0 && (
          <div className="mt-2 flex justify-between text-[10px] text-zinc-600">
            <span>
              {data[0]?.label || formatTime(data[0]?.timestamp)}
            </span>
            <span>
              {data[data.length - 1]?.label || formatTime(data[data.length - 1]?.timestamp)}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function formatTime(ts?: string): string {
  if (!ts) return "";
  const d = new Date(ts);
  return d.getHours().toString().padStart(2, "0") + ":00";
}
