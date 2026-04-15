import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getUserTTSSettings, upsertUserTTSSettings } from "@/lib/queries/users";

async function authenticate(instance: string) {
  if (!isValidInstance(instance)) {
    return { user: null, error: NextResponse.json({ error: "Invalid instance." }, { status: 400 }) };
  }
  const user = await getSessionUser();
  if (!user) {
    return { user: null, error: NextResponse.json({ error: "Not logged in." }, { status: 401 }) };
  }
  return { user, error: null };
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const { user, error } = await authenticate(instance);
  if (error) return error;

  try {
    const settings = await getUserTTSSettings(user!.user_id);
    return NextResponse.json(settings);
  } catch (e) {
    console.error("tts GET error", e);
    return NextResponse.json({ error: "Datenbankfehler." }, { status: 500 });
  }
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const { user, error } = await authenticate(instance);
  if (error) return error;

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON." }, { status: 400 });
  }

  const allowed = ["provider", "voice", "style_prompt", "model", "output_format"] as const;
  const updates: Record<string, unknown> = {};
  for (const key of allowed) {
    if (key in body) updates[key] = body[key] === "" ? null : body[key];
  }

  try {
    const settings = await upsertUserTTSSettings(user!.user_id, updates as Parameters<typeof upsertUserTTSSettings>[1]);
    return NextResponse.json(settings);
  } catch (e) {
    console.error("tts PATCH error", e);
    return NextResponse.json({ error: "Datenbankfehler." }, { status: 500 });
  }
}
