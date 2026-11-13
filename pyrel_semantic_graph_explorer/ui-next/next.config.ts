import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: { proxyTimeout: 900000 },
  async rewrites() {
    return [{ source: '/api/corporate/:path*', destination: 'http://127.0.0.1:8000/api/corporate/:path*' }];
  },
  reactStrictMode: true,
};

export default nextConfig;
