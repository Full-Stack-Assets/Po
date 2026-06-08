"use client";

import { useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { OrchestrationResult } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CheckCircle2, XCircle, Loader2, ShieldCheck, Clock } from "lucide-react";

export default function OrchestratePage() {
  const [input, setInput] = useState("");
  const [validate, setValidate] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OrchestrationResult | null>(null);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;

    setLoading(true);
    setError("");
    setResult(null);

    const res = await api.orchestrate({
      input: input.trim(),
      validate,
    });

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
        <h1 className="text-2xl font-bold">Orchestrate</h1>
        <p className="text-sm text-zinc-500">
          Run a single task through the orchestration pipeline
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <Textarea
              placeholder="Describe a task... e.g. 'Write a cold outreach email for SaaS founders about our analytics tool'"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={4}
              className="resize-none"
            />
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm text-zinc-400">
                <input
                  type="checkbox"
                  checked={validate}
                  onChange={(e) => setValidate(e.target.checked)}
                  className="rounded border-zinc-700 bg-zinc-800"
                />
                Validate before executing
              </label>
              <Button type="submit" disabled={loading || !input.trim()}>
                {loading ? (
                  <>
                    <Loader2 size={16} className="mr-2 animate-spin" />
                    Running...
                  </>
                ) : (
                  "Run Task"
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

      {result && <ResultCard result={result} />}
    </div>
  );
}

function ResultCard({ result }: { result: OrchestrationResult }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-3">
          {result.success ? (
            <CheckCircle2 size={20} className="text-green-400" />
          ) : (
            <XCircle size={20} className="text-red-400" />
          )}
          <span className="text-lg">{result.intent || "Task"}</span>
          <Badge variant="secondary">
            {result.provider_used}/{result.model_used}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Metrics */}
        <div className="flex flex-wrap gap-4 text-sm text-zinc-500">
          <span>Tokens: {(result.tokens_used ?? 0).toLocaleString()}</span>
          <span>Cost: ${(result.cost_usd ?? 0).toFixed(6)}</span>
          <span>Latency: {(result.latency_ms ?? 0).toFixed(0)}ms</span>
        </div>

        {/* Validation */}
        {result.validation && (
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} />
            <span className="text-sm">Validation:</span>
            <Badge
              variant={
                result.validation.score === "green"
                  ? "default"
                  : result.validation.score === "yellow"
                    ? "secondary"
                    : "destructive"
              }
            >
              {result.validation.score} ({result.validation.overall_score}/100)
            </Badge>
          </div>
        )}

        {/* Verification */}
        {result.verification && (
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            <span className="text-sm">Verification:</span>
            <span className="text-sm text-green-400">
              {result.verification.passed} passed
            </span>
            {result.verification.failed > 0 && (
              <span className="text-sm text-red-400">
                {result.verification.failed} failed
              </span>
            )}
            {result.refunded && (
              <Badge variant="destructive">Refunded</Badge>
            )}
          </div>
        )}

        {/* Approval */}
        {result.approval && (
          <div className="flex items-center gap-2 text-yellow-400">
            <Clock size={16} />
            <span className="text-sm">
              Awaiting approval: {result.approval.type} (id: {result.approval.id})
            </span>
          </div>
        )}

        {/* Output */}
        {result.output && (
          <div className="rounded-lg bg-zinc-900 p-4">
            <pre className="whitespace-pre-wrap text-sm text-zinc-300">
              {result.output}
            </pre>
          </div>
        )}

        {/* Error */}
        {result.error && result.error !== "awaiting_approval" && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-400">
            {result.error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
