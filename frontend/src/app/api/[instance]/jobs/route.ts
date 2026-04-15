import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const response = await client!.getJobs();
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Jobs unavailable." }, { status: 502 });
  }
}
