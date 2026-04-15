import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

/**
 * GET /api/[instance]/sessions/[id]/lock
 *
 * Returns the current execution lock status for a session.
 * { is_running: boolean, channel: "telegram" | "web" | null }
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.getLockStatus(id);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}
