import { NextResponse } from "next/server";
import { ACCESS_COOKIE, SESSION_MAX_AGE_SECONDS, createSessionToken } from "@/lib/session-auth";

function missingAuthVariables() {
  return [
    process.env.APP_PASSWORD ? "" : "APP_PASSWORD",
    process.env.SESSION_SECRET ? "" : "SESSION_SECRET",
  ].filter(Boolean);
}

function setupErrorResponse() {
  const missing = missingAuthVariables();
  const message = missing.includes("APP_PASSWORD")
    ? "APP_PASSWORD is not configured"
    : "SESSION_SECRET is not configured";

  return NextResponse.json(
    {
      ok: false,
      configured: false,
      missing,
      message,
    },
    { status: 500 },
  );
}

export async function GET() {
  const missing = missingAuthVariables();
  return NextResponse.json({
    ok: true,
    configured: missing.length === 0,
    missing,
    message: missing.includes("APP_PASSWORD")
      ? "APP_PASSWORD is not configured"
      : missing.includes("SESSION_SECRET")
        ? "SESSION_SECRET is not configured"
        : "Access gate is configured.",
  });
}

export async function POST(request: Request) {
  const configuredPassword = process.env.APP_PASSWORD;
  const sessionSecret = process.env.SESSION_SECRET;

  if (process.env.NODE_ENV === "development") {
    console.info("[auth] APP_PASSWORD present:", Boolean(configuredPassword));
  }

  if (!configuredPassword || !sessionSecret) {
    return setupErrorResponse();
  }

  const body = await request.json().catch(() => ({}));
  const password = String(body.password ?? "");

  if (password !== configuredPassword) {
    return NextResponse.json({ ok: false, message: "Invalid password." }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: ACCESS_COOKIE,
    value: await createSessionToken(sessionSecret),
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  return response;
}
