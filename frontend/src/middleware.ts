import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";

const SECRET = new TextEncoder().encode(process.env.JWT_SECRET || "dev-secret");

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip all API routes (they handle their own auth), static files, health
  if (
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  // Root page — no auth needed (returns 404 via page.tsx)
  if (pathname === "/") {
    return NextResponse.next();
  }

  // Extract instance name from path: /[instance]/...
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) {
    return NextResponse.next();
  }

  const instance = segments[0];

  // Auth pages — no auth needed (login + magic-link callback).
  // Instance validation happens in the layout (Node.js runtime) via notFound().
  if (segments[1] === "login" || (segments[1] === "auth" && segments[2] === "callback")) {
    return NextResponse.next();
  }

  // Check per-instance session cookie, then fall back to legacy global cookie
  const instanceCookie = `session_${instance}`;
  const token = request.cookies.get(instanceCookie)?.value
    || request.cookies.get("session")?.value;

  if (!token) {
    return NextResponse.redirect(new URL(`/${instance}/login`, request.url));
  }

  try {
    const { payload } = await jwtVerify(token, SECRET);
    // Verify the token is for this instance
    if (payload.instance !== instance) {
      return NextResponse.redirect(new URL(`/${instance}/login`, request.url));
    }
    // Add user info to headers for downstream use
    const response = NextResponse.next();
    response.headers.set("x-user-id", String(payload.user_id));
    response.headers.set("x-user-email", String(payload.email));
    return response;
  } catch {
    return NextResponse.redirect(new URL(`/${instance}/login`, request.url));
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
