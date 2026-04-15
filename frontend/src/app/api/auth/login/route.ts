import { NextRequest, NextResponse } from "next/server";
import { createMagicLinkToken } from "@/lib/auth";
import { sendMagicLink } from "@/lib/email";
import { getBaseUrl, getInternalApiSecret } from "@/lib/env";
import { getUserByEmail, getUserByTelegramId } from "@/lib/queries/users";
import { isValidInstance, getInstanceUrl } from "@/lib/instances";

const GENERIC_OK = { message: "ok" };

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { instance } = body;

    if (!instance) {
      return NextResponse.json(GENERIC_OK);
    }

    if (!isValidInstance(instance)) {
      return NextResponse.json(GENERIC_OK);
    }

    const email = body.email as string | undefined;
    const telegramId = body.telegram_id as string | undefined;

    if (!email && !telegramId) {
      return NextResponse.json(GENERIC_OK);
    }

    // ── Email login ─────────────────────────────────────────────
    if (email) {
      const user = await getUserByEmail(email, instance);
      if (!user) {
        return NextResponse.json(GENERIC_OK);
      }

      const token = await createMagicLinkToken(email, instance);
      await sendMagicLink(email, token, instance);
      return NextResponse.json(GENERIC_OK);
    }

    // ── Telegram ID login ───────────────────────────────────────
    if (telegramId) {
      const user = await getUserByTelegramId(telegramId, instance);
      if (!user || !user.email) {
        return NextResponse.json(GENERIC_OK);
      }

      const token = await createMagicLinkToken(user.email, instance);
      const magicLink = `${getBaseUrl()}/api/auth/verify?token=${token.trim()}`;

      // Send magic link via the bot backend's Telegram integration
      try {
        const botUrl = getInstanceUrl(instance);
        await fetch(`${botUrl}/api/v1/auth/send-login-link`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Internal-Secret": getInternalApiSecret(),
          },
          body: JSON.stringify({
            chat_id: parseInt(telegramId),
            text: `🔑 Dein Login-Link für ${instance}:\n\n${magicLink}\n\nDer Link ist 15 Minuten gültig.`,
          }),
          signal: AbortSignal.timeout(5000),
        });
      } catch {
        // Silently fail — don't reveal whether the Telegram ID exists
      }

      return NextResponse.json(GENERIC_OK);
    }

    return NextResponse.json(GENERIC_OK);
  } catch (error) {
    console.error("Login error:", error);
    return NextResponse.json(GENERIC_OK);
  }
}
