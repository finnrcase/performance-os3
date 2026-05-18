export const DEFAULT_PRODUCTION_BACKEND_API_URL = "https://api-production-b3ff.up.railway.app";

function firstConfiguredValue(values: Array<string | undefined>) {
  return values.map((value) => value?.trim()).find(Boolean) ?? "";
}

export function backendApiBaseUrl() {
  const configured = firstConfiguredValue([
    process.env.BACKEND_API_URL,
    process.env.NEXT_PUBLIC_API_URL,
    process.env.NEXT_PUBLIC_API_BASE_URL,
  ]);
  const value = configured || (process.env.NODE_ENV === "production" ? DEFAULT_PRODUCTION_BACKEND_API_URL : "");
  const cleaned = value.replace(/\/+$/, "");
  if (!cleaned) {
    throw new Error("Backend API URL is not configured. Set NEXT_PUBLIC_API_URL or BACKEND_API_URL.");
  }
  let parsed: URL;
  try {
    parsed = new URL(cleaned);
  } catch (error) {
    throw new Error(`Backend API URL is invalid: ${cleaned}`, { cause: error });
  }
  if (process.env.NODE_ENV === "production") {
    if (["localhost", "127.0.0.1", "::1"].includes(parsed.hostname)) {
      throw new Error("Production backend API URL cannot point to localhost.");
    }
  }
  return cleaned;
}
