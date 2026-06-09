import { NextResponse } from "next/server";
import crypto from "crypto";

export async function POST(req: Request, { params }: { params: { id: string } }) {
  const { content, validate } = await req.json();
  const apiKey = process.env.OPENROUTER_API_KEY;

  if (!apiKey) {
    return NextResponse.json({ detail: "No LLM provider configured" }, { status: 503 });
  }

  const userMsg = {
    id: crypto.randomUUID(),
    role: "user",
    content,
    timestamp: new Date().toISOString(),
  };

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
          { role: "user", content },
        ],
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: { message: res.statusText } }));
      return NextResponse.json({
        detail: `OpenRouter error: ${err.error?.message || res.statusText}`,
      }, { status: 502 });
    }

    const data = await res.json();
    const latency = Date.now() - start;
    const reply = data.choices?.[0]?.message?.content || "No response";
    const usage = data.usage || {};

    const assistantMsg = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: reply,
      timestamp: new Date().toISOString(),
      metadata: {
        model: data.model || "openai/gpt-4.1-mini",
        provider: "openrouter",
        latency_ms: latency,
        tokens_used: (usage.prompt_tokens || 0) + (usage.completion_tokens || 0),
        cost_usd: 0,
      },
    };

    return NextResponse.json({
      user_message: userMsg,
      assistant_message: assistantMsg,
      result: {
        success: true,
        intent: "chat",
        model_used: data.model || "openai/gpt-4.1-mini",
        provider_used: "openrouter",
        output: reply,
        cost_usd: 0,
        tokens_used: (usage.prompt_tokens || 0) + (usage.completion_tokens || 0),
        latency_ms: latency,
      },
    });
  } catch (err: any) {
    return NextResponse.json({
      detail: `LLM call failed: ${err.message}`,
    }, { status: 502 });
  }
}
