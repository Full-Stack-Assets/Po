import { NextResponse } from "next/server";

export async function GET(req: Request, { params }: { params: { id: string } }) {
  return NextResponse.json({
    id: params.id,
    title: "Conversation",
    messages: [],
    metadata: {},
  });
}

export async function DELETE(req: Request, { params }: { params: { id: string } }) {
  return NextResponse.json({ deleted: true, id: params.id });
}
