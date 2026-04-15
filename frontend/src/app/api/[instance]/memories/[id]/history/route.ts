import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getMemoryById, getMemoryHistory } from "@/lib/es";

export async function GET(
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
    const history = await getMemoryHistory(id, user.user_id);
    return NextResponse.json(history);
  } catch (e) {
    console.error("memory history GET error", e);
    return NextResponse.json({ error: "Failed to load." }, { status: 500 });
  }
}
