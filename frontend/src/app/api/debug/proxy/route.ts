import { NextResponse, type NextRequest } from "next/server";
import { backendApiBaseUrl } from "@/lib/backend-api";
import { ACCESS_COOKIE, isValidSessionToken } from "@/lib/session-auth";

async function fetchProbe(url: string, cookieHeader?: string) {
  const started = performance.now();
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      signal: AbortSignal.timeout(30_000),
    });
    const text = await response.text();
    return {
      target: url,
      status: response.status,
      ok: response.ok,
      durationMs: Math.round(performance.now() - started),
      responseText: text.slice(0, 2000),
    };
  } catch (error) {
    return {
      target: url,
      status: null,
      ok: false,
      durationMs: Math.round(performance.now() - started),
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export async function GET(request: NextRequest) {
  const sessionSecret = process.env.SESSION_SECRET;
  if (!sessionSecret) {
    return NextResponse.json({ status: "error", detail: "SESSION_SECRET is not configured" }, { status: 500 });
  }

  const token = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!(await isValidSessionToken(token, sessionSecret))) {
    return NextResponse.json({ status: "error", detail: token ? "Session expired" : "Authentication required" }, { status: 401 });
  }

  const backendBaseUrl = backendApiBaseUrl();
  const cookieHeader = token ? `${ACCESS_COOKIE}=${encodeURIComponent(token)}` : undefined;
  const healthTarget = `${backendBaseUrl}/health`;
  const coreTarget = `${backendBaseUrl}/api/dashboard/core`;

  console.info(`[api-debug-proxy] probing health ${healthTarget}`);
  const health = await fetchProbe(healthTarget);
  console.info(`[api-debug-proxy] probing dashboard core ${coreTarget}`);
  const dashboardCore = await fetchProbe(coreTarget, cookieHeader);

  return NextResponse.json({
    status: dashboardCore.ok ? "ok" : "degraded",
    backendBaseUrl,
    rewrites: {
      sameOriginDashboardCore: "/api/dashboard/core",
      railwayDashboardCore: coreTarget,
      note: "The catch-all Next route maps /api/:path* to `${backendApiBaseUrl()}/api/:path*`; this endpoint probes Railway directly from Vercel/Next.",
    },
    health,
    dashboardCore,
    generatedAt: new Date().toISOString(),
  });
}
