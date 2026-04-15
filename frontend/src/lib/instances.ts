const allowedInstances = new Set(
  (process.env.ALLOWED_INSTANCES || "banana-bot")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
);

export function isValidInstance(name: string): boolean {
  return allowedInstances.has(name);
}

export function getInstanceUrl(name: string): string {
  // BACKEND_URL env var points to the backend service (docker-compose: http://backend:8080)
  return process.env.BACKEND_URL || "http://backend:8080";
}

export function getAllInstances(): string[] {
  return Array.from(allowedInstances);
}
