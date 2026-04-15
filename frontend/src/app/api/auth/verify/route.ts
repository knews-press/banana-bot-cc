import { NextRequest, NextResponse } from "next/server";
import { verifyToken } from "@/lib/auth";
import { getBaseUrl } from "@/lib/env";
import { getUserByEmail } from "@/lib/queries/users";

interface MagicLinkPayload {
  email: string;
  instance: string;
  purpose: string;
}

export async function GET(request: NextRequest) {
  const baseUrl = getBaseUrl();
  const token = request.nextUrl.searchParams.get("token");
  if (!token) {
    return NextResponse.redirect(new URL("/", baseUrl));
  }

  const payload = await verifyToken<MagicLinkPayload>(token);
  if (!payload || payload.purpose !== "magic-link") {
    return NextResponse.redirect(
      new URL(`/?error=invalid-token`, baseUrl)
    );
  }

  const user = await getUserByEmail(payload.email, payload.instance);
  if (!user) {
    return NextResponse.redirect(
      new URL(`/${payload.instance}/login?error=not-found`, baseUrl)
    );
  }

  // Redirect to client-side callback page with the original token.
  // Setting a cookie directly on a server-side redirect is blocked by iOS Safari's
  // ITP (Intelligent Tracking Prevention) when the link originates from an external
  // source (e.g. email). The callback page exchanges the token via a same-origin
  // fetch, which iOS treats as first-party and allows the cookie to be set.
  return NextResponse.redirect(
    new URL(`/${payload.instance}/auth/callback?token=${encodeURIComponent(token)}`, baseUrl)
  );
}
