import { NextResponse, type NextRequest } from "next/server";
import { DEFAULT_PRODUCTION_BACKEND_API_URL, backendApiBaseUrl } from "@/lib/backend-api";
import { ACCESS_COOKIE, isValidSessionToken } from "@/lib/session-auth";

export async function GET(request: NextRequest) {
  const started = performance.now();
  const sessionSecret = process.env.SESSION_SECRET;
  if (!sessionSecret) {
    return NextResponse.json({ status: "error", detail: "SESSION_SECRET is not configured" }, { status: 500 });
  }

  const token = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!(await isValidSessionToken(token, sessionSecret))) {
    return NextResponse.json({ status: "error", detail: token ? "Session expired" : "Authentication required" }, { status: 401 });
  }

  const configuredBackend = backendApiBaseUrl();
  const target = `${DEFAULT_PRODUCTION_BACKEND_API_URL}/api/dashboard/core`;
  const cookieHeader = `${ACCESS_COOKIE}=${encodeURIComponent(token ?? "")}`;

  console.info(`[api-debug-proxy-dashboard-core] GET ${target}`);
  try {
    const response = await fetch(target, {
      cache: "no-store",
      headers: { cookie: cookieHeader },
      signal: AbortSignal.timeout(120_000),
    });
    const text = await response.text();
    const durationMs = Math.round(performance.now() - started);
    console.info(`[api-debug-proxy-dashboard-core] ${response.status} in ${durationMs}ms`);
    return NextResponse.json({
      status: response.ok ? "ok" : "error",
      configuredBackend,
      target,
      httpStatus: response.status,
      durationMs,
      responseText: text.slice(0, 4000),
      generatedAt: new Date().toISOString(),
    });
  } catch (error) {
    const durationMs = Math.round(performance.now() - started);
    console.error(`[api-debug-proxy-dashboard-core] failed in ${durationMs}ms`, error);
    return NextResponse.json(
      {
        status: "error",
        configuredBackend,
        target,
        httpStatus: null,
        durationMs,
        errorMessage: error instanceof Error ? error.message : String(error),
        generatedAt: new Date().toISOString(),
      },
      { status: 502 },
    );
  }
}
