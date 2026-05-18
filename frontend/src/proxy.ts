import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, isValidSessionToken } from "@/lib/session-auth";

export async function proxy(request: NextRequest) {
  const sessionSecret = process.env.SESSION_SECRET;
  const isLoginPage = request.nextUrl.pathname === "/login";

  if (!sessionSecret) {
    if (isLoginPage) {
      return NextResponse.next();
    }
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("setup", "missing");
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  const cookieValue = request.cookies.get(ACCESS_COOKIE)?.value;

  if (await isValidSessionToken(cookieValue, sessionSecret)) {
    if (isLoginPage) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }

  if (isLoginPage) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
