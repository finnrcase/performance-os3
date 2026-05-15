import { NextResponse, type NextRequest } from "next/server";

function backendBaseUrl() {
  return (
    process.env.BACKEND_API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8001"
  ).replace(/\/$/, "");
}

export function GET(request: NextRequest) {
  const target = new URL(`${backendBaseUrl()}/api/strava/callback`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.set(key, value);
  });
  return NextResponse.redirect(target, 303);
}
