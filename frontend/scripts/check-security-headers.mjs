import assert from "node:assert/strict";
import { createVercelConfig } from "../vercel.mjs";

const production = createVercelConfig({ environment: "production" });
const previewWithoutApi = createVercelConfig({ environment: "preview" });
const previewWithStaging = createVercelConfig({
  environment: "preview",
  backendApiOrigin: "https://api-staging.example.test",
});

const globalRule = production.headers?.find((rule) => rule.source === "/(.*)");
assert.ok(globalRule, "Vercel must apply the security policy to every response");

const headers = new Map(globalRule.headers.map(({ key, value }) => [key.toLowerCase(), value]));
for (const header of [
  "content-security-policy",
  "referrer-policy",
  "x-content-type-options",
  "x-frame-options",
  "permissions-policy",
  "strict-transport-security",
]) {
  assert.ok(headers.has(header), `Missing required response header: ${header}`);
}

const csp = headers.get("content-security-policy");
for (const directive of [
  "default-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "script-src 'self'",
  "upgrade-insecure-requests",
]) {
  assert.ok(csp.includes(directive), `CSP is missing ${directive}`);
}

assert.equal(headers.get("x-content-type-options"), "nosniff");
assert.equal(headers.get("x-frame-options"), "DENY");
assert.ok(csp.includes("connect-src 'self'"), "API requests should stay same-origin through the Vercel proxy");
assert.ok(
  production.rewrites.some((rule) => rule.destination.startsWith("https://api-production-81629.up.railway.app/")),
  "Production must keep its configured backend proxy",
);
assert.equal(
  previewWithoutApi.rewrites.some((rule) => rule.source.startsWith("/api/")),
  false,
  "Preview must not route API requests to production by default",
);
assert.ok(
  previewWithStaging.rewrites.some((rule) => rule.destination.startsWith("https://api-staging.example.test/")),
  "A preview can use an explicitly configured staging backend",
);
assert.throws(
  () => createVercelConfig({
    environment: "preview",
    backendApiOrigin: "https://api-production-81629.up.railway.app",
  }),
  /Non-production deployments cannot route to the production backend/,
);
assert.equal(
  previewWithStaging.rewrites.some((rule) => rule.destination.includes("api-production-81629")),
  false,
  "Preview must not fall back to production when a staging backend is configured",
);

console.log("Vercel security headers and production/preview API isolation are valid.");
