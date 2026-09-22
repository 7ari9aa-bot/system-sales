/** @type {import('next').NextConfig} */

/**
 * Browser-facing security boundary (review G-07).
 *
 * The API middleware protects Railway responses, but dashboard documents are
 * served by Vercel, so those headers never reached the browser. Keep this
 * policy at the edge that actually serves HTML and JS.
 *
 * Next App Router needs inline bootstrap/style tags unless the application is
 * converted to nonce-based CSP. `unsafe-inline` is therefore narrowly limited
 * to scripts/styles for compatibility; external scripts remain forbidden and
 * every other resource type is allowlisted.
 */
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
let apiOrigin = "http://localhost:8000";
try {
  apiOrigin = new URL(apiUrl).origin;
} catch {
  // Do not make the frontend build fail from a malformed optional env var.
  // The API client will surface its own clear failure; use the local fallback
  // in the CSP so this config remains deterministic.
}

const apiWebSocketOrigin = apiOrigin
  .replace(/^https:/, "wss:")
  .replace(/^http:/, "ws:");

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  // See the module comment: remove unsafe-inline only with a nonce strategy.
  // Dev-only relaxation: Next.js dev server (React Refresh / HMR) evaluates
  // inline scripts, so without 'unsafe-eval' every page breaks under
  // `next dev` — production builds stay strict.
  ...(process.env.NODE_ENV === "production"
    ? ["script-src 'self' 'unsafe-inline'"]
    : ["script-src 'self' 'unsafe-inline' 'unsafe-eval'"]),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin} ${apiWebSocketOrigin}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
].join("; ");

export const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  // HSTS only in production builds. Note this also covers `next start` run
  // locally, because that sets NODE_ENV=production — verified. That is safe:
  // RFC 6797 §2.3.1 excludes IP literals from HSTS, and the production host is
  // a real domain. A development server (`next dev`) never sends it.
  ...(process.env.NODE_ENV === "production"
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains; preload",
        },
      ]
    : []),
];

const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
