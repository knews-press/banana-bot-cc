import { NextRequest } from "next/server";
import { getAuthenticatedClient } from "@/lib/proxy";

/**
 * GET /api/[instance]/sessions/[id]/stream
 *
 * Proxies the backend SSE stream for live session events.
 * Web clients subscribe here to get real-time tool/text events
 * regardless of whether execution was triggered from Telegram or web.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ instance: string; id: string }> }
) {
  const { instance, id } = await params;
  const [client, error] = await getAuthenticatedClient(instance);
  if (error) return error;

  try {
    const backendRes = await client!.streamSession(id, request.signal);

    if (!backendRes.ok) {
      return new Response("Backend-Stream nicht verfügbar.", { status: 502 });
    }

    // Pass the SSE stream straight through to the browser
    return new Response(backendRes.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no", // disable nginx buffering
      },
    });
  } catch (err) {
    return new Response("Stream error.", { status: 502 });
  }
}
