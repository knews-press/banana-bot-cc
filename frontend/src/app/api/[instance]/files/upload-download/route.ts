import { NextRequest, NextResponse } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

export async function GET(req: NextRequest, { params }: { params: Promise<{ instance: string }> }) {
  const { instance } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error || !client) return error ?? NextResponse.json({ error: "Error" }, { status: 401 });
  const uploadId = req.nextUrl.searchParams.get("upload_id") ?? "";
  if (!uploadId) return NextResponse.json({ error: "Missing upload_id." }, { status: 400 });
  try {
    const res = await client.downloadUpload(uploadId);
    if (!res.ok) return NextResponse.json({ error: "Nicht gefunden." }, { status: res.status });
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
