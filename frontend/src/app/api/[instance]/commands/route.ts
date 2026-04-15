import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export const dynamic = "force-dynamic";

/** GET /api/{instance}/commands — Return command registry for autocomplete. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.getCommands();
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err) {
    console.error("Commands registry proxy error:", err);
    return NextResponse.json(
      { error: "Backend nicht erreichbar." },
      { status: 502 }
    );
  }
}

/** POST /api/{instance}/commands — Execute a slash command. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const body = await request.json();
    const response = await client!.executeCommand(body.command, body.args || []);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err) {
    console.error("Command execute proxy error:", err);
    return NextResponse.json(
      { error: "Backend nicht erreichbar." },
      { status: 502 }
    );
  }
}
