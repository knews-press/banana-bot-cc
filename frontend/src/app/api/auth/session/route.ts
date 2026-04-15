import { NextRequest, NextResponse } from "next/server";
import { verifyToken, createSessionToken, sessionCookieName, sessionCookieOptions } from "@/lib/auth";
import { getUserByEmail } from "@/lib/queries/users";
import { getApiKeyForUser, createApiKeyForUser } from "@/lib/queries/api-keys";
import { randomBytes } from "crypto";

interface MagicLinkPayload {
  email: string;
  instance: string;
  purpose: string;
}

/**
 * POST /api/auth/session
 *
 * Exchanges a magic-link token for a session cookie.
 * Called client-side from the /auth/callback page so that the cookie is set
 * in response to a same-origin fetch — iOS Safari's ITP allows this, whereas
 * it blocks cookies set on server-side redirects from external link sources.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const token = body.token as string | undefined;

  if (!token) {
    return NextResponse.json({ error: "Token fehlt." }, { status: 400 });
  }

  const payload = await verifyToken<MagicLinkPayload>(token);
  if (!payload || payload.purpose !== "magic-link") {
    return NextResponse.json({ error: "Invalid or expired link." }, { status: 401 });
  }

  const user = await getUserByEmail(payload.email, payload.instance);
  if (!user) {
    return NextResponse.json({ error: "Kein Zugang zu dieser Instanz." }, { status: 403 });
  }

  // Ensure user has an API key for bot access
  let apiKey = await getApiKeyForUser(user.user_id);
  if (!apiKey) {
    apiKey = `sk-bb-${randomBytes(32).toString("base64url")}`;
    await createApiKeyForUser(user.user_id, "web-frontend", apiKey);
  }

  const sessionToken = await createSessionToken({
    user_id: user.user_id,
    email: payload.email,
    display_name: user.display_name,
    instance: payload.instance,
  });

  const response = NextResponse.json({
    ok: true,
    instance: payload.instance,
  });

  // Per-instance cookie name (global path) so multiple instances can coexist
  response.cookies.set(
    sessionCookieName(payload.instance),
    sessionToken,
    sessionCookieOptions(),
  );

  return response;
}
