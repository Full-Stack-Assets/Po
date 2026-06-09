import { NextResponse } from "next/server";
import crypto from "crypto";

export async function POST(req: Request) {
  const { email, password } = await req.json();
  if (!email || !password) {
    return NextResponse.json({ detail: "Email and password required" }, { status: 400 });
  }
  const id = crypto.randomUUID();
  const token = Buffer.from(JSON.stringify({ sub: id, email, exp: Date.now() + 86400000 })).toString("base64url");
  return NextResponse.json({
    user: { id, email, name: email.split("@")[0] },
    access_token: token,
    token_type: "bearer",
  });
}
