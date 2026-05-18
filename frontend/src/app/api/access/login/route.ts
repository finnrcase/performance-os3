import { NextResponse } from "next/server";
import { backendApiBaseUrl } from "@/lib/backend-api";
import { ACCESS_COOKIE, SESSION_MAX_AGE_SECONDS, createSessionToken } from "@/lib/session-auth";

function missingAuthVariables() {
  return [
    process.env.SESSION_SECRET ? "" : "SESSION_SECRET",
    process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL ? "" : "NEXT_PUBLIC_API_URL or BACKEND_API_URL",
  ].filter(Boolean);
}

function setupErrorResponse() {
  const missing = missingAuthVariables();
  const message = missing.includes("SESSION_SECRET")
    ? "SESSION_SECRET is not configured"
    : "Backend API URL is not configured";

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

function clearAccessCookie(response: NextResponse) {
  response.cookies.set({
    name: ACCESS_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: process.env.NODE_ENV === "production" ? "none" : "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}

async function authenticateWithBackend(password: string): Promise<{ ok: true } | { ok: false; status: number; message: string }> {
  let target: string;
  try {
    target = `${backendApiBaseUrl()}/api/auth/login`;
  } catch {
    return {
      ok: false,
      status: 500,
      message: "Backend API URL is not configured. Set NEXT_PUBLIC_API_URL or BACKEND_API_URL on Vercel.",
    };
  }

  try {
    const response = await fetch(target, {
      method: "POST",
      cache: "no-store",
      redirect: "manual",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (response.ok) {
      return { ok: true };
    }
    if (response.status === 401 || response.status === 403) {
      return { ok: false, status: 401, message: "Invalid password." };
    }
    const body = await response.json().catch(() => null);
    return {
      ok: false,
      status: response.status >= 500 ? 502 : response.status,
      message: body?.detail
        ? `Backend login failed: ${body.detail}`
        : "Backend login failed. Confirm APP_PASSWORD and SESSION_SECRET are set on Railway.",
    };
  } catch {
    return {
      ok: false,
      status: 502,
      message: "Could not reach the Railway backend login endpoint. Confirm NEXT_PUBLIC_API_URL points to the live FastAPI service.",
    };
  }
}

async function verifyBackendSession(sessionToken: string): Promise<{ ok: true } | { ok: false; status: number; message: string }> {
  let target: string;
  try {
    target = `${backendApiBaseUrl()}/api/auth/session`;
  } catch {
    return {
      ok: false,
      status: 500,
      message: "Backend API URL is not configured. Set NEXT_PUBLIC_API_URL or BACKEND_API_URL on Vercel.",
    };
  }

  try {
    const response = await fetch(target, {
      cache: "no-store",
      redirect: "manual",
      headers: {
        Cookie: `${ACCESS_COOKIE}=${sessionToken}`,
      },
    });
    if (response.ok) {
      return { ok: true };
    }
    if (response.status === 401 || response.status === 403) {
      return {
        ok: false,
        status: 401,
        message: "Backend rejected this session. Confirm SESSION_SECRET matches on Vercel and Railway, then log in again.",
      };
    }
    const body = await response.json().catch(() => null);
    return {
      ok: false,
      status: 502,
      message: body?.detail
        ? `Backend auth check failed: ${body.detail}`
        : "Backend auth check failed. Confirm APP_PASSWORD and SESSION_SECRET are set on Railway.",
    };
  } catch {
    return {
      ok: false,
      status: 502,
      message: "Could not verify the session with the Railway backend. Confirm NEXT_PUBLIC_API_URL points to the live FastAPI service.",
    };
  }
}

export async function GET() {
  const missing = missingAuthVariables();
  return NextResponse.json({
    ok: true,
    configured: missing.length === 0,
    missing,
    message: missing.includes("SESSION_SECRET")
      ? "SESSION_SECRET is not configured"
      : missing.length
        ? "Backend API URL is not configured."
        : "Access gate is configured.",
  });
}

export async function POST(request: Request) {
  const sessionSecret = process.env.SESSION_SECRET;

  if (process.env.NODE_ENV === "development") {
    console.info("[auth] SESSION_SECRET present:", Boolean(sessionSecret));
  }

  if (missingAuthVariables().length || !sessionSecret) {
    return setupErrorResponse();
  }

  const body = await request.json().catch(() => ({}));
  const password = String(body.password ?? "");

  const backendAuth = await authenticateWithBackend(password);
  if (!backendAuth.ok) {
    const response = NextResponse.json({ ok: false, message: backendAuth.message }, { status: backendAuth.status });
    clearAccessCookie(response);
    return response;
  }

  const sessionToken = await createSessionToken(sessionSecret);
  const backendCheck = await verifyBackendSession(sessionToken);
  if (!backendCheck.ok) {
    const response = NextResponse.json({ ok: false, message: backendCheck.message }, { status: backendCheck.status });
    clearAccessCookie(response);
    return response;
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set({
    name: ACCESS_COOKIE,
    value: sessionToken,
    httpOnly: true,
    sameSite: process.env.NODE_ENV === "production" ? "none" : "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  return response;
}
