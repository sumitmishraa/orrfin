/**
 * Next.js config. The browser calls the API through /api/* on the web app's own origin,
 * and Next forwards it to FastAPI. The login cookie therefore belongs to the web app, so
 * it is sent with every same-origin request and never needs cross-site settings.
 */
import type { NextConfig } from "next";

// Where the web server (not the browser) reaches the API. Read when `next dev`/`next start` boots.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
  },
};

export default nextConfig;
