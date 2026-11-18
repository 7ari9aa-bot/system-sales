import { APP_PATH_PREFIXES, legacyPublicRedirects } from "./src/lib/public-seo-routes.mjs";

const PRODUCTION_API_ORIGIN = "https://p01--system-sales--smkyc4wjfbtq.code.run";

function normalizeApiOrigin(value) {
  if (!value) return null;

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("BACKEND_API_ORIGIN must be a valid HTTPS origin.");
  }

  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("BACKEND_API_ORIGIN must be an HTTPS origin without credentials or a path.");
  }

  return parsed.origin;
}

export function createVercelConfig({
  environment = process.env.VERCEL_ENV,
  backendApiOrigin = process.env.BACKEND_API_ORIGIN,
} = {}) {
  // Production keeps its existing API unless the deployment explicitly
  // overrides it. Preview has no backend by default: pointing a preview at
  // production can turn ordinary QA actions into live customer-data writes.
  const configuredOrigin = backendApiOrigin?.trim();
  const apiOrigin = normalizeApiOrigin(
    configuredOrigin || (environment === "production" ? PRODUCTION_API_ORIGIN : ""),
  );
  if (environment !== "production" && apiOrigin === PRODUCTION_API_ORIGIN) {
    throw new Error("Non-production deployments cannot route to the production backend.");
  }

  const rewrites = [];
  if (apiOrigin) {
    rewrites.push(
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
      {
        source: "/auth/:path*",
        destination: `${apiOrigin}/auth/:path*`,
      },
    );
  }
  // Only real SPA screens fall back to index.html (dashboard, cashier, auth...).
  // Public marketing pages are prerendered files, so Vercel serves them before
  // any rewrite. Everything else must be a true 404, otherwise every mistyped
  // URL answers 200 with the home page (a "soft 404" that Google penalises).
  rewrites.push({
    source: `/(${APP_PATH_PREFIXES.join("|")})/:path*`,
    destination: "/index.html",
  });
  rewrites.push({
    source: `/(${APP_PATH_PREFIXES.join("|")})`,
    destination: "/index.html",
  });

  return {
    headers: [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self' https://connect.facebook.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob: https:; media-src 'self' data: blob: https:; connect-src 'self' https://connect.facebook.net https://www.facebook.com https://graph.facebook.com; frame-src 'self' https://www.facebook.com https://web.facebook.com; worker-src 'self' blob:; upgrade-insecure-requests",
          },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          // The assistant dictates questions with the browser's speech recognition, which needs the
          // microphone for THIS origin only. Camera and location stay off; no third party gets any.
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
      // Plain-text and Markdown files for AI assistants: explicit UTF-8 so Arabic
      // is read correctly, and a short cache so edits reach crawlers quickly.
      {
        source: "/(.*)\\.md",
        headers: [
          { key: "Content-Type", value: "text/markdown; charset=utf-8" },
          { key: "Cache-Control", value: "public, max-age=0, s-maxage=3600, must-revalidate" },
        ],
      },
      {
        source: "/(llms[a-z-]*\\.txt)",
        headers: [
          { key: "Content-Type", value: "text/plain; charset=utf-8" },
          { key: "Cache-Control", value: "public, max-age=0, s-maxage=3600, must-revalidate" },
        ],
      },
    ],
    rewrites,
    // The pre-country addresses (/pricing, /en/pricing...) moved under /{country}/{lang}/. A
    // permanent redirect keeps old bookmarks and indexed links alive instead of a 404.
    redirects: legacyPublicRedirects().map((r) => ({ ...r, permanent: true })),
    // Unknown paths get the static 404 page with a real 404 status.
    // (Vercel only applies this after files and rewrites have been tried.)
  };
}

export const config = createVercelConfig();
