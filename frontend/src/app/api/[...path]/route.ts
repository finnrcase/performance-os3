import { NextResponse, type NextRequest } from "next/server";
import { backendApiBaseUrl } from "@/lib/backend-api";
import { ACCESS_COOKIE, isValidSessionToken } from "@/lib/session-auth";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function jsonUnauthorized(message = "Authentication required") {
  return NextResponse.json({ detail: message, code: "auth_required" }, { status: 401 });
}

function forwardedHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("accept-encoding");
  return headers;
}

function isPublicBackendApiPath(path: string[]) {
  return path.join("/") === "auth/login" || path.join("/") === "auth/logout";
}

async function proxyToBackend(request: NextRequest, context: RouteContext) {
  const sessionSecret = process.env.SESSION_SECRET;
  if (!sessionSecret) {
    return NextResponse.json({ detail: "SESSION_SECRET is not configured", code: "auth_not_configured" }, { status: 500 });
  }

  const token = request.cookies.get(ACCESS_COOKIE)?.value;
  const { path } = await context.params;
  if (!isPublicBackendApiPath(path) && !(await isValidSessionToken(token, sessionSecret))) {
    return jsonUnauthorized(token ? "Session expired" : "Authentication required");
  }

  try {
    const joinedPath = path.map(encodeURIComponent).join("/");
    const target = new URL(`${backendApiBaseUrl()}/api/${joinedPath}`);
    request.nextUrl.searchParams.forEach((value, key) => {
      target.searchParams.append(key, value);
    });
    const method = request.method.toUpperCase();
    const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
    const shouldTraceDashboardCore = joinedPath === "dashboard/core";
    const started = performance.now();
    if (shouldTraceDashboardCore) {
      console.info(`[api-proxy] ${method} /api/dashboard/core -> ${target.toString()}`);
    }
    const backendResponse = await fetch(target, {
      method,
      headers: forwardedHeaders(request),
      body,
      cache: "no-store",
      redirect: "manual",
    });
    if (shouldTraceDashboardCore) {
      console.info(`[api-proxy] ${method} /api/dashboard/core <- ${backendResponse.status} in ${Math.round(performance.now() - started)}ms`);
    }

    const responseHeaders = new Headers(backendResponse.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("transfer-encoding");
    return new NextResponse(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("[api-proxy] backend request failed", error);
    return NextResponse.json(
      { detail: "Backend API proxy could not reach FastAPI.", code: "backend_unreachable" },
      { status: 502 },
    );
  }
}

export const GET = proxyToBackend;
export const POST = proxyToBackend;
export const PUT = proxyToBackend;
export const PATCH = proxyToBackend;
export const DELETE = proxyToBackend;
export const HEAD = proxyToBackend;
