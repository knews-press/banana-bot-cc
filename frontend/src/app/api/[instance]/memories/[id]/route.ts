import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getMemoryById, deleteMemory, updateMemory } from "@/lib/es";

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  if (!isValidInstance(instance)) return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  let body: { type?: string; name?: string; description?: string; content?: string; tags?: string[] };
  try { body = await req.json(); } catch { return NextResponse.json({ error: "Invalid JSON." }, { status: 400 }); }

  if (!body.name || !body.content) {
    return NextResponse.json({ error: "name und content sind erforderlich." }, { status: 400 });
  }

  try {
    const memory = await getMemoryById(id);
    if (!memory || memory.user_id !== user.user_id) {
      return NextResponse.json({ error: "Memory not found." }, { status: 404 });
    }
    await updateMemory(id, {
      type: body.type || "user",
      name: body.name,
      description: body.description || "",
      content: body.content,
      tags: body.tags,
    });
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("memory PUT error", e);
    return NextResponse.json({ error: "Save failed." }, { status: 500 });
  }
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  if (!isValidInstance(instance)) return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  try {
    const memory = await getMemoryById(id);
    if (!memory || memory.user_id !== user.user_id) {
      return NextResponse.json({ error: "Memory not found." }, { status: 404 });
    }
    await deleteMemory(id);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("memory DELETE error", e);
    return NextResponse.json({ error: "Elasticsearch error." }, { status: 500 });
  }
}
