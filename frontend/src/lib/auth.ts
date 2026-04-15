import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";

const SECRET = new TextEncoder().encode(process.env.JWT_SECRET || "dev-secret");

interface TokenPayload {
  user_id: number;
  email: string;
  display_name: string | null;
  instance: string;
}

export async function createSessionToken(payload: TokenPayload): Promise<string> {
  return new SignJWT({ ...payload })
    .setProtectedHeader({ alg: "HS256" })
    .setExpirationTime("7d")
    .setIssuedAt()
    .sign(SECRET);
}

export async function createMagicLinkToken(email: string, instance: string): Promise<string> {
  return new SignJWT({ email, instance, purpose: "magic-link" })
    .setProtectedHeader({ alg: "HS256" })
    .setExpirationTime("15m")
    .setIssuedAt()
    .sign(SECRET);
}

export async function verifyToken<T = TokenPayload>(token: string): Promise<T | null> {
  try {
    const { payload } = await jwtVerify(token, SECRET);
    return payload as T;
  } catch {
    return null;
  }
}

export async function getSessionUser(instance?: string): Promise<TokenPayload | null> {
  const cookieStore = await cookies();

  // 1. Try instance-specific cookie if instance is known
  if (instance) {
    const token = cookieStore.get(sessionCookieName(instance))?.value;
    if (token) return verifyToken<TokenPayload>(token);
  }

  // 2. Try any session_* cookie (for /api/[instance] routes that don't pass instance)
  const allCookies = cookieStore.getAll();
  for (const cookie of allCookies) {
    if (cookie.name.startsWith("session_") && cookie.value) {
      const payload = await verifyToken<TokenPayload>(cookie.value);
      if (payload) {
        if (instance && payload.instance !== instance) continue;
        return payload;
      }
    }
  }

  // 3. Fallback: legacy global "session" cookie (for existing sessions after upgrade)
  const legacyToken = cookieStore.get("session")?.value;
  if (!legacyToken) return null;
  const payload = await verifyToken<TokenPayload>(legacyToken);
  if (payload && instance && payload.instance !== instance) return null;
  return payload;
}

/** Per-instance cookie name, e.g. "session_knitterbot" */
export function sessionCookieName(instance: string): string {
  return `session_${instance}`;
}

/** Cookie options — global path so all routes (including /api) can read it.
 *  Isolation comes from the per-instance cookie NAME, not the path. */
export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: true,
    sameSite: "lax" as const,
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: "/",
  };
}
