import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy API requests to the FastAPI backend
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8420/api/:path*",
      },
    ];
  },
};

export default nextConfig;
