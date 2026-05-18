import { NextResponse } from "next/server";
import { backendApiBaseUrl } from "@/lib/backend-api";
import { ACCESS_COOKIE, SESSION_MAX_AGE_SECONDS, createSessionToken } from "@/lib/session-auth";

type AuthConfig =
  | {
      ok: true;
      sessionSecret: string;
      backendUrl: string;
    }
  | {
      ok: false;
      missing: string[];
      message: string;
      backendUrlError?: string;
    };

function resolveAuthConfig(): AuthConfig {
  const sessionSecret = process.env.SESSION_SECRET?.trim();
  const missing: string[] = [];
  let backendUrl = "";
  let backendUrlError = "";

  if (!sessionSecret) {
    missing.push("SESSION_SECRET");
  }

  try {
    backendUrl = backendApiBaseUrl();
  } catch (error) {
    backendUrlError = error instanceof Error ? error.message : "Backend API URL resolver failed.";
    missing.push("BACKEND_API_URL");
  }

  if (!sessionSecret || !backendUrl) {
    const messageParts = [];
    if (!sessionSecret) {
      messageParts.push("SESSION_SECRET is not configured on Vercel.");
    }
    if (!backendUrl) {
      messageParts.push(`Backend URL resolver failed: ${backendUrlError}`);
    }
    return {
      ok: false,
      missing,
      message: messageParts.join(" "),
      backendUrlError,
    };
  }

  return { ok: true, sessionSecret, backendUrl };
}

function missingAuthVariables(config: AuthConfig = resolveAuthConfig()) {
  return config.ok ? [] : config.missing;
}

function setupErrorResponse(config: Exclude<AuthConfig, { ok: true }>) {
  return NextResponse.json(
    {
      ok: false,
      configured: false,
      missing: missingAuthVariables(config),
      message: config.message,
      backendUrlError: config.backendUrlError,
    },
    { status: 500 },
  );
}

function clearAccessCookie(response: NextResponse) {
  response.cookies.set({
    name: ACCESS_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}

async function authenticateWithBackend(
  backendUrl: string,
  password: string,
): Promise<{ ok: true } | { ok: false; status: number; message: string }> {
  const target = `${backendUrl}/api/auth/login`;

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
      message: `Backend unreachable: could not reach ${backendUrl}. Confirm the Railway FastAPI service is live and reachable from Vercel.`,
    };
  }
}

async function verifyBackendSession(
  backendUrl: string,
  sessionToken: string,
): Promise<{ ok: true } | { ok: false; status: number; message: string }> {
  const target = `${backendUrl}/api/auth/session`;

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
      message: `Backend unreachable: could not verify the session with ${backendUrl}. Confirm the Railway FastAPI service is live and reachable from Vercel.`,
    };
  }
}

export async function GET() {
  const config = resolveAuthConfig();
  const missing = missingAuthVariables(config);
  return NextResponse.json({
    ok: true,
    configured: config.ok,
    missing,
    backendUrl: config.ok ? config.backendUrl : null,
    backendUrlError: config.ok ? null : config.backendUrlError,
    message: config.ok ? "Access gate is configured." : config.message,
  });
}

export async function POST(request: Request) {
  const config = resolveAuthConfig();

  if (process.env.NODE_ENV === "development") {
    console.info("[auth] SESSION_SECRET present:", config.ok || !missingAuthVariables(config).includes("SESSION_SECRET"));
  }

  if (!config.ok) {
    return setupErrorResponse(config);
  }

  const body = await request.json().catch(() => ({}));
  const password = String(body.password ?? "");

  const backendAuth = await authenticateWithBackend(config.backendUrl, password);
  if (!backendAuth.ok) {
    const response = NextResponse.json({ ok: false, message: backendAuth.message }, { status: backendAuth.status });
    clearAccessCookie(response);
    return response;
  }

  const sessionToken = await createSessionToken(config.sessionSecret);
  const backendCheck = await verifyBackendSession(config.backendUrl, sessionToken);
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
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  return response;
}
