/**
 * Branding utilities — converts an instance name into display strings.
 *
 * Keeps things simple: the instance name IS the brand name.
 * No hardcoded mapping needed — any new instance automatically gets
 * a sensible display name derived from its identifier.
 */

/** Returns a human-readable display name for an instance. */
export function getDisplayName(instance: string): string {
  return instance;
}

/** Returns the page title for an instance (used in <title> tags). */
export function getPageTitle(instance: string): string {
  return instance;
}

/** Returns the email "from" display name for an instance. */
export function getEmailFrom(instance: string): string {
  return instance;
}
