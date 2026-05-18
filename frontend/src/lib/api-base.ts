const LOCAL_BACKEND_API_URL = "http://localhost:8001";

export function publicApiBaseUrl() {
  const configured = (process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
  if (process.env.NODE_ENV === "production") {
    return "";
  }
  if (configured && process.env.NEXT_PUBLIC_USE_DIRECT_API !== "true") {
    return "";
  }
  if (configured) {
    return configured;
  }
  return LOCAL_BACKEND_API_URL;
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
