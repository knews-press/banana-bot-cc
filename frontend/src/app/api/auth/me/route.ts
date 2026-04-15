import { NextRequest, NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth";

export async function GET(request: NextRequest) {
  const instance = request.nextUrl.searchParams.get("instance") || undefined;
  const user = await getSessionUser(instance);
  if (!user) {
    return NextResponse.json({ error: "Not logged in." }, { status: 401 });
  }
  return NextResponse.json(user);
}
