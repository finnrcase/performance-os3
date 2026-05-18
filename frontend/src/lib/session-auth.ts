export const ACCESS_COOKIE = "performance_os_access";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function base64UrlEncode(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export async function signSession(timestamp: string, secret: string) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(timestamp));
  return base64UrlEncode(new Uint8Array(signature));
}

export async function createSessionToken(secret: string) {
  const timestamp = Date.now().toString();
  return `${timestamp}.${await signSession(timestamp, secret)}`;
}

export async function isValidSessionToken(token: string | undefined, secret: string) {
  if (!token) return false;
  const [timestamp, signature] = token.split(".");
  const timestampNumber = Number(timestamp);

  if (!timestamp || !signature || !Number.isFinite(timestampNumber)) {
    return false;
  }

  if (Date.now() - timestampNumber > SESSION_MAX_AGE_SECONDS * 1000) {
    return false;
  }

  return signature === (await signSession(timestamp, secret));
}
