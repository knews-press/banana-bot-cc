import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error || !client) return error ?? NextResponse.json({ error: "No client" }, { status: 500 });

  const sp = req.nextUrl.searchParams;
  const searchParams: Parameters<typeof client.getGraphSearch>[0] = {};
  if (sp.get("domain")) searchParams.domain = sp.get("domain")!;
  if (sp.get("types")) searchParams.types = sp.get("types")!.split(",");
  if (sp.get("q")) searchParams.q = sp.get("q")!;
  if (sp.get("limit")) searchParams.limit = Number(sp.get("limit"));

  try {
    const response = await client.getGraphSearch(searchParams);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Backend nicht erreichbar." }, { status: 502 });
  }
}
