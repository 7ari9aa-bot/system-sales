const PRODUCTION_API_ORIGIN = "https://api-production-81629.up.railway.app";

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
  rewrites.push({
    source: "/((?!api/|auth/).*)",
    destination: "/index.html",
  });

  return {
    headers: [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob: https:; media-src 'self' data: blob: https:; connect-src 'self'; frame-src 'self'; worker-src 'self' blob:; upgrade-insecure-requests",
          },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ],
    rewrites,
  };
}

export const config = createVercelConfig();
