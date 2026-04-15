import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.getSession(id);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.deleteSession(id);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}
