export function backendApiBaseUrl() {
  const value = process.env.BACKEND_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  const cleaned = value.replace(/\/$/, "");
  if (!cleaned) {
    throw new Error("BACKEND_API_URL or NEXT_PUBLIC_API_URL is required for OAuth callback forwarding.");
  }
  return cleaned;
}
