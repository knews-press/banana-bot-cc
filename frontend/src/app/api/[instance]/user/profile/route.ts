import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getUserProfile, updateUserProfile } from "@/lib/queries/users";

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
    const profile = await getUserProfile(user!.user_id);
    if (!profile) return NextResponse.json({ error: "User not found." }, { status: 404 });
    return NextResponse.json(profile);
  } catch (e) {
    console.error("profile GET error", e);
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

  // Allowed top-level fields
  const allowedProfileFields = ["display_name"] as const;
  const allowedPrefFields = [
    "permission_mode", "model", "thinking", "max_turns",
    "budget", "verbose", "working_directory",
    "language", "github_username", "github_org",
    "custom_instructions",
  ] as const;

  const updates: Parameters<typeof updateUserProfile>[1] = {};

  for (const key of allowedProfileFields) {
    if (key in body) updates[key] = body[key] as string;
  }

  const prefUpdates: Record<string, unknown> = {};
  for (const key of allowedPrefFields) {
    if (key in body) prefUpdates[key] = body[key];
  }
  if (Object.keys(prefUpdates).length > 0) {
    updates.preferences = prefUpdates as Parameters<typeof updateUserProfile>[1]["preferences"];
  }

  try {
    await updateUserProfile(user!.user_id, updates);
    const profile = await getUserProfile(user!.user_id);
    return NextResponse.json(profile);
  } catch (e) {
    console.error("profile PATCH error", e);
    return NextResponse.json({ error: "Datenbankfehler." }, { status: 500 });
  }
}
