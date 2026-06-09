import { NextResponse } from "next/server";

export async function GET() {
  const hasKey = !!process.env.OPENROUTER_API_KEY;
  return NextResponse.json({
    initialized: true,
    agents: [
      { id: "1", name: "ResearchAgent", capabilities: ["research", "summarization"], intents: ["research", "lookup", "find", "search"], active: 0 },
      { id: "2", name: "WriterAgent", capabilities: ["writing", "summarization"], intents: ["write", "draft", "compose", "create", "email", "blog"], active: 0 },
      { id: "3", name: "CodeAgent", capabilities: ["code_generation", "analysis"], intents: ["code", "implement", "debug", "refactor", "build"], active: 0 },
      { id: "4", name: "AnalysisAgent", capabilities: ["analysis", "planning"], intents: ["analyze", "compare", "evaluate", "assess", "plan"], active: 0 },
    ],
    constraints: [
      { name: "token_budget", max: 100000, used: 0, remaining: 100000, utilization: "0.0%", unit: "tokens", exceeded: false },
      { name: "cost_budget", max: 5.0, used: 0, remaining: 5.0, utilization: "0.0%", unit: "USD", exceeded: false },
      { name: "latency_budget", max: 30000, used: 0, remaining: 30000, utilization: "0.0%", unit: "ms", exceeded: false },
    ],
    providers: hasKey
      ? [{ provider: "openrouter", total_requests: 0, success_rate: "100.0%", avg_latency_ms: 0, consecutive_failures: 0, circuit_open: false }]
      : [],
    usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0, total_cost_usd: 0 },
    models: hasKey ? [
      { model: "openai/gpt-4.1-mini", provider: "openrouter", name: "GPT-4.1 Mini", context_window: 1047576, cost_input_1k: 0.0004, cost_output_1k: 0.0016, capabilities: ["research", "writing", "code", "analysis"] },
      { model: "anthropic/claude-sonnet-4-5", provider: "openrouter", name: "Claude Sonnet 4.5", context_window: 200000, cost_input_1k: 0.003, cost_output_1k: 0.015, capabilities: ["writing", "code", "analysis", "research"] },
      { model: "google/gemini-2.5-flash", provider: "openrouter", name: "Gemini 2.5 Flash", context_window: 1048576, cost_input_1k: 0.00015, cost_output_1k: 0.0006, capabilities: ["summarization", "fast"] },
    ] : [],
  });
}
