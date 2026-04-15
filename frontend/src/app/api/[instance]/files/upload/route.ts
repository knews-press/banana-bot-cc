import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { getApiKeyForUser } from "@/lib/queries/api-keys";
import { isValidInstance, getInstanceUrl } from "@/lib/instances";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;

  if (!isValidInstance(instance))
    return NextResponse.json({ error: "Invalid instance." }, { status: 400 });

  const user = await getSessionUser();
  if (!user)
    return NextResponse.json({ error: "Not logged in." }, { status: 401 });

  const apiKey = await getApiKeyForUser(user.user_id);
  if (!apiKey)
    return NextResponse.json({ error: "No API key." }, { status: 403 });

  try {
    // Pipe raw body directly to backend — avoids re-serialising FormData
    // which corrupts the multipart boundary in some Node.js / Next.js versions.
    const contentType = req.headers.get("content-type") ?? "";
    const body = await req.arrayBuffer();

    const res = await fetch(`${getInstanceUrl(instance)}/api/v1/files/upload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": contentType,
      },
      body,
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ error: "Bot nicht erreichbar." }, { status: 502 });
  }
}
