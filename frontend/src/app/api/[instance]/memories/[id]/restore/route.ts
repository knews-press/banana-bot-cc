import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getMemoryById, restoreMemoryVersion } from "@/lib/es";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  if (!isValidInstance(instance)) return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  let body: { version?: number };
  try { body = await req.json(); } catch { return NextResponse.json({ error: "Invalid JSON." }, { status: 400 }); }

  if (typeof body.version !== "number") {
    return NextResponse.json({ error: "version (number) ist erforderlich." }, { status: 400 });
  }

  try {
    const memory = await getMemoryById(id);
    if (!memory || memory.user_id !== user.user_id) {
      return NextResponse.json({ error: "Memory not found." }, { status: 404 });
    }
    await restoreMemoryVersion(id, body.version, user.user_id);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("memory restore POST error", e);
    return NextResponse.json({ error: "Restore failed." }, { status: 500 });
  }
}
