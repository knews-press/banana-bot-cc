import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";
import { isValidInstance } from "@/lib/instances";
import { getDailyStats, getToolStats } from "@/lib/queries/users";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ instance: string }> }
) {
  const { instance } = await params;
  if (!isValidInstance(instance)) {
    return NextResponse.json({ error: "Invalid instance." }, { status: 400 });
  }
  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "Not logged in." }, { status: 401 });
  }
  try {
    const [daily, tools] = await Promise.all([
      getDailyStats(user.user_id),
      getToolStats(user.user_id),
    ]);
    return NextResponse.json({ daily, tools });
  } catch (e) {
    console.error("daily stats GET error", e);
    return NextResponse.json({ error: "Datenbankfehler." }, { status: 500 });
  }
}
