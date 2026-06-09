import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const { input } = await req.json();
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    return NextResponse.json({ detail: "No LLM provider configured" }, { status: 503 });
  }

  const start = Date.now();
  try {
    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://full-stack-assets.github.io/Po/",
        "X-Title": "Po AI Operator",
      },
      body: JSON.stringify({
        model: "openai/gpt-4.1-mini",
        messages: [
          { role: "system", content: "You are Po, an AI growth operator for B2B micro-SaaS founders. You help with research, analysis, content creation, code, and strategy. Be concise and actionable." },
          { role: "user", content: input },
        ],
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: { message: res.statusText } }));
      return NextResponse.json({
        success: false,
        error: `OpenRouter error: ${err.error?.message || res.statusText}`,
      }, { status: 502 });
    }

    const data = await res.json();
    const latency = Date.now() - start;
    const usage = data.usage || {};

    return NextResponse.json({
      success: true,
      intent: "chat",
      model_used: data.model || "openai/gpt-4.1-mini",
      provider_used: "openrouter",
      output: data.choices?.[0]?.message?.content || "No response",
      cost_usd: 0,
      tokens_used: (usage.prompt_tokens || 0) + (usage.completion_tokens || 0),
      latency_ms: latency,
    });
  } catch (err: any) {
    return NextResponse.json({
      success: false,
      error: `LLM call failed: ${err.message}`,
    }, { status: 502 });
  }
}
