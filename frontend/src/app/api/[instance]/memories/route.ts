import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { searchMemories, createMemory } from "@/lib/es";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  if (!isValidInstance(instance)) return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  const q = req.nextUrl.searchParams.get("q") || undefined;
  try {
    const memories = await searchMemories(user.user_id, q);
    return NextResponse.json(memories);
  } catch (e) {
    console.error("memories GET error", e);
    return NextResponse.json({ error: "Elasticsearch error." }, { status: 500 });
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  if (!isValidInstance(instance)) return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  let body: { type?: string; name?: string; description?: string; content?: string; tags?: string[] };
  try { body = await req.json(); } catch { return NextResponse.json({ error: "Invalid JSON." }, { status: 400 }); }

  if (!body.name || !body.content) {
    return NextResponse.json({ error: "name und content sind erforderlich." }, { status: 400 });
  }

  try {
    const id = await createMemory(user.user_id, {
      type: body.type || "user",
      name: body.name,
      description: body.description || "",
      content: body.content,
      tags: body.tags,
    });
    return NextResponse.json({ id }, { status: 201 });
  } catch (e) {
    console.error("memories POST error", e);
    return NextResponse.json({ error: "Elasticsearch error." }, { status: 500 });
  }
}
