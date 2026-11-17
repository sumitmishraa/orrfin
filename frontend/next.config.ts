/**
 * Next.js config. The browser calls the API through /api/* on the web app's own origin,
 * and Next forwards it to FastAPI. The login cookie therefore belongs to the web app, so
 * it is sent with every same-origin request and never needs cross-site settings.
 *
 * It also sets the browser security headers for every page (BUILD_PLAN §9, v3.0 change 50).
 */
import type { NextConfig } from "next";

// Where the web server (not the browser) reaches the API. Read when `next dev`/`next start` boots.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const isDev = process.env.NODE_ENV !== "production";

/**
 * Content Security Policy: what a page may load and where it may send data.
 * - Everything comes from Orrfin's own address ('self'); no third-party scripts, frames or forms.
 * - 'unsafe-inline' for scripts is required by Next.js's own inline bootstrap; the dev server
 *   also needs 'unsafe-eval' for hot reload, so that is allowed in development only.
 * - frame-ancestors 'self': no other website can put Orrfin in a frame (clickjacking), while
 *   the invoice page can still show an uploaded file in a frame of its own.
 */
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "frame-src 'self'",
  "frame-ancestors 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

const nextConfig: NextConfig = {
  // Development only: lets someone open the laptop's dev server through a free Cloudflare quick
  // tunnel (https://<words>.trycloudflare.com). Without it Next blocks the tunnel's requests.
  allowedDevOrigins: ["*.trycloudflare.com"],
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
