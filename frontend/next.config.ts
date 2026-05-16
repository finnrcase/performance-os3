import type { NextConfig } from "next";

const backendApiUrl = (process.env.NEXT_PUBLIC_API_URL ?? process.env.BACKEND_API_URL ?? "").replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    if (!backendApiUrl) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
