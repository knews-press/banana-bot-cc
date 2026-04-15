/**
 * Centralized environment variable access.
 *
 * All env-var lookups with fallback defaults live here so they are easy to
 * find, easy to change, and never silently hardcoded in random files.
 */

/** Public base URL for magic links, redirects, etc. */
export function getBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_BASE_URL || "http://localhost:3000").trim().replace(/\/$/, "");
}

/** Shared secret for internal API calls (bot <-> web). */
export function getInternalApiSecret(): string {
  return process.env.INTERNAL_API_SECRET || "internal";
}
