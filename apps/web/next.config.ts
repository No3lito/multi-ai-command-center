import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * Production builds are a static export (apps/web/out) served by the FastAPI
 * backend at the same origin. Rewrites do not apply to static exports, so the
 * /api proxy to the backend exists only for `npm run dev`.
 */
const DEV_API_TARGET = process.env.CC_DEV_API_TARGET ?? "http://127.0.0.1:8000";

export default function config(phase: string): NextConfig {
  const base: NextConfig = {
    reactStrictMode: true,
    images: { unoptimized: true },
    poweredByHeader: false,
  };

  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return {
      ...base,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${DEV_API_TARGET}/api/:path*` }];
      },
    };
  }

  return { ...base, output: "export" };
}
