"use client";

import { useEffect, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { StatusResponse, StatsResponse, HealthResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Activity,
  CheckCircle2,
  DollarSign,
  Zap,
  ShieldCheck,
  RefreshCw,
} from "lucide-react";

export default function DashboardPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const [s, st, h] = await Promise.all([
        api.getStatus(),
        api.getStats(),
        api.getHealth(),
      ]);
      if (isApiError(s) || isApiError(st) || isApiError(h)) {
        const err = [s, st, h].find(isApiError);
        setError(err?.error || "API error");
        return;
      }
      setStatus(s);
      setStats(st);
      setHealth(h);
      setError("");
    } catch (e: any) {
      setError(e.message || "Failed to connect to backend");
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, []);

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

  if (!status || !stats) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-zinc-800" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-lg bg-zinc-900" />
          ))}
        </div>
      </div>
    );
  }

  const costConstraint = status.constraints.find((c) => c.unit === "USD");
  const tokenConstraint = status.constraints.find((c) => c.unit === "tokens");
  const successPct = Math.round((stats.success_rate ?? 0) * 100);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-zinc-500">
            Real-time operator status
          </p>
        </div>
        <button
          onClick={refresh}
          className="rounded-lg border border-zinc-800 p-2 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title="Total Runs"
          value={stats.total_runs.toLocaleString()}
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
          title="Verified"
          value={stats.verified_runs.toLocaleString()}
          icon={<ShieldCheck size={18} />}
          color="blue"
        />
        <KPICard
          title="Refunded"
          value={stats.refunded_runs.toLocaleString()}
          icon={<DollarSign size={18} />}
          color={stats.refunded_runs > 0 ? "yellow" : "green"}
        />
      </div>

      {/* Constraints */}
      <div className="grid gap-4 sm:grid-cols-2">
        {costConstraint && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-400">
                <DollarSign size={14} />
                Cost Budget
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-2xl font-bold">
                  ${costConstraint.used.toFixed(4)}
                </span>
                <span className="text-sm text-zinc-500">
                  / ${costConstraint.max.toFixed(2)}
                </span>
              </div>
              <Progress
                value={Math.min((costConstraint.used / costConstraint.max) * 100, 100)}
              />
            </CardContent>
          </Card>
        )}
        {tokenConstraint && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-400">
                <Zap size={14} />
                Token Budget
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-2 flex items-baseline justify-between">
                <span className="text-2xl font-bold">
                  {tokenConstraint.used.toLocaleString()}
                </span>
                <span className="text-sm text-zinc-500">
                  / {tokenConstraint.max.toLocaleString()}
                </span>
              </div>
              <Progress
                value={Math.min(
                  (tokenConstraint.used / tokenConstraint.max) * 100,
                  100
                )}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Providers & Agents */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-zinc-400">
              Providers
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {status.providers.length === 0 ? (
                <p className="text-sm text-zinc-600">No providers configured</p>
              ) : (
                status.providers.map((p) => (
                  <div
                    key={p.provider}
                    className="flex items-center justify-between rounded-lg border border-zinc-800 px-4 py-2"
                  >
                    <span className="text-sm font-medium">{p.provider}</span>
                    <Badge variant={p.circuit_open ? "destructive" : "default"}>
                      {p.circuit_open ? "Down" : "Healthy"}
                    </Badge>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-zinc-400">
              Agents
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {status.agents.map((a) => (
                <Badge key={a.name} variant="secondary">
                  {a.name}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Health */}
      {health && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-400">
              System Health
              <Badge variant={health.status === "healthy" ? "default" : "destructive"}>
                {health.status}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-lg bg-zinc-900 p-4 text-xs text-zinc-400">
              {JSON.stringify(health.usage, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

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
            <p className={`mt-1 text-2xl font-bold ${colors[color]}`}>{value}</p>
          </div>
          <div className={`rounded-lg bg-zinc-800 p-2 ${colors[color]}`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
