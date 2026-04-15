import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const instance = body.instance as string | undefined;

  const response = NextResponse.json({ message: "Abgemeldet." });

  // Clear per-instance cookie
  if (instance) {
    response.cookies.set(`session_${instance}`, "", {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      maxAge: 0,
      path: "/",
    });
  }

  // Also clear legacy global cookie
  response.cookies.set("session", "", {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });

  return response;
}
