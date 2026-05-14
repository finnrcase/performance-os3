import { NextResponse, type NextRequest } from "next/server";

const ACCESS_COOKIE = "performance_os_access";

export function proxy(request: NextRequest) {
  const accessPassword = process.env.APP_ACCESS_PASSWORD;

  if (!accessPassword) {
    return NextResponse.next();
  }

  const isLoginPage = request.nextUrl.pathname === "/login";
  const cookieValue = request.cookies.get(ACCESS_COOKIE)?.value;

  if (cookieValue === accessPassword) {
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
  matcher: ["/((?!api/access|_next/static|_next/image|favicon.ico).*)"],
};
