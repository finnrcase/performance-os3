import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // API forwarding is handled by src/app/api/[...path]/route.ts so auth checks
  // and session-cookie handling always run before requests reach FastAPI.
};

export default nextConfig;
