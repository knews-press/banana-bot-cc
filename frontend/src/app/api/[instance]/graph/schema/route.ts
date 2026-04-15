import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getGraphSchema } from "@/lib/es";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  if (!isValidInstance(instance))
    return NextResponse.json({ error: "Invalid instance." }, { status: 400 });

  const user = await getSessionUser();
  if (!user)
    return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  try {
    const schema = await getGraphSchema(user.user_id);
    if (!schema) return NextResponse.json(null);
    // Parse the JSON content so the client receives a real object
    try {
      const parsed = JSON.parse(schema.content);
      return NextResponse.json(parsed);
    } catch {
      return NextResponse.json(null);
    }
  } catch (e) {
    console.error("graph schema error", e);
    return NextResponse.json({ error: "Schema error." }, { status: 500 });
  }
}
