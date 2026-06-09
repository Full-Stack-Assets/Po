import { NextResponse } from "next/server";
import crypto from "crypto";

export async function GET() {
  return NextResponse.json({ conversations: [] });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const id = crypto.randomUUID();
  return NextResponse.json({
    id,
    title: body.title || "New conversation",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    status: "active",
    messages: [],
    metadata: {},
  });
}
