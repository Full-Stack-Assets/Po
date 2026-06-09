import { NextResponse } from "next/server";

export async function GET() {
  const hasKey = !!process.env.OPENROUTER_API_KEY;
  return NextResponse.json({
    providers: hasKey
      ? [{
          provider: "openrouter",
          enabled: true,
          api_key_set: true,
          default_model: "openai/gpt-4.1-mini",
          models_available: ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4-5", "google/gemini-2.5-flash"],
          health: { circuit_open: false, success_rate: 1.0, avg_latency_ms: 0 },
        }]
      : [],
    constraints: [
      { name: "token_budget", current_used: 0, max_value: 100000, unit: "tokens" },
      { name: "cost_budget", current_used: 0, max_value: 5.0, unit: "USD" },
    ],
    trust: { auto_approve: true, live_signals: false, fail_on_unverified: false, approval_ttl_seconds: 3600, validation_threshold: "green" },
    tools: [
      { name: "web_research", description: "Search the web for information" },
      { name: "send_email", description: "Send transactional email via Resend" },
      { name: "content_generator", description: "Generate marketing content" },
    ],
    environment: "production",
  });
}

export async function PUT() {
  return NextResponse.json({ status: "updated" });
}
