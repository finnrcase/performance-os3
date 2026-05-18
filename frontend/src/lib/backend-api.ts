const DEFAULT_PRODUCTION_BACKEND_API_URL = "https://api-production-b3ff.up.railway.app";

export function backendApiBaseUrl() {
  const value =
    process.env.BACKEND_API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    (process.env.NODE_ENV === "production" ? DEFAULT_PRODUCTION_BACKEND_API_URL : "");
  const cleaned = value.replace(/\/$/, "");
  if (!cleaned) {
    throw new Error("BACKEND_API_URL or NEXT_PUBLIC_API_URL is required for OAuth callback forwarding.");
  }
  if (process.env.NODE_ENV === "production") {
    const parsed = new URL(cleaned);
    if (["localhost", "127.0.0.1", "::1"].includes(parsed.hostname)) {
      throw new Error("Production backend API URL cannot point to localhost.");
    }
  }
  return cleaned;
}
