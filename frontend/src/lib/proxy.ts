import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { getApiKeyForUser } from "@/lib/queries/api-keys";
import { isValidInstance } from "@/lib/instances";
import { BotApiClient } from "@/lib/bot-api";

/**
 * Get an authenticated BotApiClient for the current request.
 * Returns [client, errorResponse] - if errorResponse is set, return it immediately.
 */
export async function getAuthenticatedClient(
  instance: string
): Promise<[BotApiClient | null, NextResponse | null]> {
  if (!isValidInstance(instance)) {
    return [null, NextResponse.json({ error: "Invalid instance." }, { status: 400 })];
  }

  const user = await getSessionUser();
  if (!user) {
    return [null, NextResponse.json({ error: "Not logged in." }, { status: 401 })];
  }

  const apiKey = await getApiKeyForUser(user.user_id);
  if (!apiKey) {
    return [null, NextResponse.json({ error: "No API key." }, { status: 403 })];
  }

  return [new BotApiClient(instance, apiKey), null];
}
