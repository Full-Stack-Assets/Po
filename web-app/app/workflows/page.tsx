"use client";

import { useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { WorkflowPlanResponse, OrchestrationResult } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  GitBranch,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
} from "lucide-react";

export default function WorkflowsPage() {
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WorkflowPlanResponse | null>(null);
  const [error, setError] = useState("");

  async function handlePlan(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim()) return;

    setLoading(true);
    setError("");
    setResult(null);

    const res = await api.planWorkflow({ goal: goal.trim() });

    setLoading(false);
    if (isApiError(res)) {
      setError(res.error);
    } else {
      setResult(res);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Workflows</h1>
        <p className="text-sm text-zinc-500">
          Plan and execute multi-step workflows from a high-level goal
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handlePlan} className="space-y-4">
            <Textarea
              placeholder="Describe your goal... e.g. 'Launch a Product Hunt campaign for our analytics SaaS including landing page, email sequence, and social posts'"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={3}
              className="resize-none"
            />
            <div className="flex justify-end">
              <Button type="submit" disabled={loading || !goal.trim()}>
                {loading ? (
                  <>
                    <Loader2 size={16} className="mr-2 animate-spin" />
                    Planning & Executing...
                  </>
                ) : (
                  <>
                    <GitBranch size={16} className="mr-2" />
                    Plan & Run
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {result && <WorkflowPlanResponseCard result={result} />}
    </div>
  );
}

function WorkflowPlanResponseCard({ result }: { result: WorkflowPlanResponse }) {
  const statusColor =
    result.status === "completed"
      ? "default"
      : result.status === "awaiting_approval"
        ? "secondary"
        : "destructive";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3 text-lg">
          <GitBranch size={20} className="text-violet-400" />
          Workflow
          <Badge variant={statusColor}>{result.status}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {result.plan_raw && (
          <div className="rounded-lg bg-zinc-900 p-3">
            <p className="mb-1 text-xs font-medium text-zinc-500">Plan</p>
            <p className="text-sm text-zinc-400">{result.plan_raw}</p>
          </div>
        )}

        {result.results && result.results.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-zinc-500">Steps</p>
            {result.results.map((step: OrchestrationResult, i: number) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg border border-zinc-800 p-3"
              >
                <div className="mt-0.5">
                  {step.success ? (
                    <CheckCircle2 size={16} className="text-green-400" />
                  ) : (
                    <XCircle size={16} className="text-red-400" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-zinc-400">
                      Step {i + 1}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {step.intent || "task"}
                    </Badge>
                    <span className="text-xs text-zinc-600">
                      ${(step.cost_usd ?? 0).toFixed(4)}
                    </span>
                  </div>
                  {step.output && (
                    <p className="mt-1 truncate text-sm text-zinc-400">
                      {step.output.slice(0, 120)}...
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {result.error && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-400">
            {result.error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
