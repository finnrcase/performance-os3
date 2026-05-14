import { NextResponse } from "next/server";

const ACCESS_COOKIE = "performance_os_access";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function missingAuthVariables() {
  return [
    process.env.APP_PASSWORD ? "" : "APP_PASSWORD",
    process.env.SESSION_SECRET ? "" : "SESSION_SECRET",
  ].filter(Boolean);
}

function setupErrorResponse() {
  const missing = missingAuthVariables();
  return NextResponse.json(
    {
      ok: false,
      configured: false,
      missing,
      message: `Performance OS access is not configured. Set ${missing.join(" and ")} in your environment.`,
    },
    { status: 500 },
  );
}

async function signSession(timestamp: string, secret: string) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(timestamp));
  return btoa(String.fromCharCode(...new Uint8Array(signature))).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function createSessionToken(secret: string) {
  const timestamp = Date.now().toString();
  return `${timestamp}.${await signSession(timestamp, secret)}`;
}

export async function GET() {
  const missing = missingAuthVariables();
  return NextResponse.json({
    ok: true,
    configured: missing.length === 0,
    missing,
    message: missing.length ? `Set ${missing.join(" and ")} before using private access.` : "Access gate is configured.",
  });
}

export async function POST(request: Request) {
  const configuredPassword = process.env.APP_PASSWORD;
  const sessionSecret = process.env.SESSION_SECRET;

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
