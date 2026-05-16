import { NextResponse, type NextRequest } from "next/server";
import { backendApiBaseUrl } from "@/lib/backend-api";

export function GET(request: NextRequest) {
  const target = new URL(`${backendApiBaseUrl()}/api/withings/callback`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.set(key, value);
  });
  return NextResponse.redirect(target, 303);
}
