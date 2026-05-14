import { NextResponse } from "next/server";

const ACCESS_COOKIE = "performance_os_access";

export async function POST(request: Request) {
  const configuredPassword = process.env.APP_ACCESS_PASSWORD;

  if (!configuredPassword) {
    return NextResponse.json({ ok: true, message: "Access gate is not configured." });
  }

  const body = await request.json().catch(() => ({}));
  const password = String(body.password ?? "");

  if (password !== configuredPassword) {
    return NextResponse.json({ ok: false, message: "Invalid password." }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: ACCESS_COOKIE,
    value: configuredPassword,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });

  return response;
}
