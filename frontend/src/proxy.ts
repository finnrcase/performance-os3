import { NextResponse, type NextRequest } from "next/server";

const ACCESS_COOKIE = "performance_os_access";
const SESSION_MAX_AGE_MS = 60 * 60 * 24 * 30 * 1000;

async function signSession(timestamp: string, secret: string) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(timestamp));
  return btoa(String.fromCharCode(...new Uint8Array(signature))).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function isValidSessionToken(token: string | undefined, secret: string) {
  if (!token) return false;
  const [timestamp, signature] = token.split(".");
  const timestampNumber = Number(timestamp);

  if (!timestamp || !signature || !Number.isFinite(timestampNumber)) {
    return false;
  }

  if (Date.now() - timestampNumber > SESSION_MAX_AGE_MS) {
    return false;
  }

  return signature === (await signSession(timestamp, secret));
}

export async function proxy(request: NextRequest) {
  const accessPassword = process.env.APP_PASSWORD;
  const sessionSecret = process.env.SESSION_SECRET;
  const isLoginPage = request.nextUrl.pathname === "/login";

  if (!accessPassword || !sessionSecret) {
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
  matcher: ["/((?!api/access|api/strava|api/integrations/strava/callback|_next/static|_next/image|favicon.ico).*)"],
};
