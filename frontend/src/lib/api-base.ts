const LOCAL_BACKEND_API_URL = "http://localhost:8001";

export function publicApiBaseUrl() {
  const configured = (process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
  if (configured && process.env.NEXT_PUBLIC_USE_DIRECT_API !== "true") {
    return "";
  }
  if (configured) {
    return configured;
  }
  if (process.env.NODE_ENV !== "production") {
    return LOCAL_BACKEND_API_URL;
  }
  throw new Error("NEXT_PUBLIC_API_URL is required in production so the frontend can reach the FastAPI backend.");
}

export function publicApiUrl(path: string) {
  return `${publicApiBaseUrl()}${path}`;
}

export function publicApiBaseLabel() {
  try {
    return publicApiBaseUrl() || "same-origin /api proxy";
  } catch {
    return "Vercel proxy /api";
  }
}
