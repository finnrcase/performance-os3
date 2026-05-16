export function backendApiBaseUrl() {
  const configured = (process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
  if (configured) {
    return configured;
  }
  if (process.env.NODE_ENV === "development") {
    return "http://localhost:8001";
  }
  throw new Error("NEXT_PUBLIC_API_URL must be set to the Railway backend URL in production.");
}
