import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

/**
 * GET /api/[instance]/sessions/active-lock
 *
 * Returns whether ANY session for the authenticated user is currently
 * locked and by which channel. Used by the web UI to detect Telegram
 * activity across all sessions.
 *
 * { is_running: boolean, channel: "telegram" | "web" | null, session_id: string | null }
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.getActiveLock();
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}
