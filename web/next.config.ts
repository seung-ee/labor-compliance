import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // /api/* 는 FastAPI(api.py)로 넘긴다. 브라우저는 같은 출처만 부르므로 CORS가 필요 없다.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  // 프록시 기본 타임아웃은 30초다(next/dist/server/lib/router-utils/proxy-request.js).
  // /ask 는 Haiku 라우팅 + Opus 생성이고, 게이트에 막혀 재생성하면 30초를 넘길 수 있다.
  experimental: { proxyTimeout: 120_000 },
};

export default nextConfig;
