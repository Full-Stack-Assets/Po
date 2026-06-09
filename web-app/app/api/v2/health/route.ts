import { NextResponse } from "next/server";

export async function GET() {
  const hasKey = !!process.env.OPENROUTER_API_KEY;
  return NextResponse.json({
    status: "healthy",
    providers: hasKey
      ? [{ provider: "openrouter", total_requests: 0, success_rate: "100.0%", avg_latency_ms: 0, consecutive_failures: 0, circuit_open: false }]
      : [],
    usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0, total_cost_usd: 0 },
  });
}
