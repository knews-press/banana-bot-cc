import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error || !client) return error ?? NextResponse.json({ error: "Error" }, { status: 401 });

  const path = req.nextUrl.searchParams.get("path") ?? "";
  const workspace = req.nextUrl.searchParams.get("workspace") === "true";
  const inline = req.nextUrl.searchParams.get("inline") === "true";
  if (!path) return NextResponse.json({ error: "Kein Pfad angegeben." }, { status: 400 });

  try {
    const res = await client.downloadFile(path, workspace, inline);
    if (!res.ok) {
      return NextResponse.json({ error: "File not found." }, { status: res.status });
    }
    const contentType = res.headers.get("content-type") ?? "application/octet-stream";
    const contentDisposition = res.headers.get("content-disposition") ?? "";
    const body = await res.arrayBuffer();
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        ...(contentDisposition ? { "Content-Disposition": contentDisposition } : {}),
      },
    });
  } catch {
    return NextResponse.json({ error: "Bot nicht erreichbar." }, { status: 502 });
  }
}
