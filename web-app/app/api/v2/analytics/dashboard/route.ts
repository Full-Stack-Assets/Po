import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    total_runs: 0,
    total_cost_usd: 0,
    total_tokens: 0,
    success_rate: 0,
    avg_latency_ms: 0,
    active_providers: process.env.OPENROUTER_API_KEY ? 1 : 0,
    pending_approvals: 0,
    cost_trend: [],
    runs_trend: [],
    cost_by_provider: [],
    cost_by_intent: [],
    provider_metrics: process.env.OPENROUTER_API_KEY
      ? [{ provider: "openrouter", total_requests: 0, success_count: 0, failure_count: 0, avg_latency_ms: 0, total_cost_usd: 0, circuit_open: false }]
      : [],
    top_intents: [],
  });
}
