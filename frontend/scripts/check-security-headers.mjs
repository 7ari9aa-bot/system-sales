/**
 * Assert the browser-facing security header policy (review G-07).
 *
 * These headers are the only thing protecting dashboard documents, which Vercel
 * serves — the API's middleware never sees them. A silent regression here is
 * invisible until someone audits the response, so it is checked in CI.
 *
 * Run: node scripts/check-security-headers.mjs
 */

import { securityHeaders } from "../next.config.mjs";

const byKey = new Map(securityHeaders.map((h) => [h.key.toLowerCase(), h.value]));

const REQUIRED = [
  "content-security-policy",
  "x-content-type-options",
  "x-frame-options",
  "referrer-policy",
  "permissions-policy",
];

const problems = [];

for (const key of REQUIRED) {
  if (!byKey.has(key)) problems.push(`missing header: ${key}`);
}

const csp = byKey.get("content-security-policy") ?? "";
const directives = new Map(
  csp
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [name, ...rest] = part.split(/\s+/);
      return [name, rest];
    }),
);

for (const name of ["default-src", "base-uri", "object-src", "frame-ancestors", "form-action"]) {
  if (!directives.has(name)) problems.push(`CSP missing directive: ${name}`);
}

if (directives.get("default-src")?.join(" ") !== "'self'") {
  problems.push("CSP default-src must be 'self'");
}
if (directives.get("object-src")?.join(" ") !== "'none'") {
  problems.push("CSP object-src must be 'none'");
}
if (directives.get("frame-ancestors")?.join(" ") !== "'none'") {
  problems.push("CSP frame-ancestors must be 'none'");
}
if (directives.get("base-uri")?.join(" ") !== "'self'") {
  problems.push("CSP base-uri must be 'self'");
}

// The API origin must be reachable, or every request from the browser fails.
const connectSrc = (directives.get("connect-src") ?? []).join(" ");
if (!connectSrc.includes("'self'")) {
  problems.push("CSP connect-src must include 'self'");
}
if (connectSrc.includes("*")) {
  problems.push("CSP connect-src must not use a wildcard");
}

if (byKey.get("x-frame-options") !== "DENY") {
  problems.push("X-Frame-Options must be DENY");
}
if (byKey.get("x-content-type-options") !== "nosniff") {
  problems.push("X-Content-Type-Options must be nosniff");
}

// unsafe-inline is a deliberate, documented App Router concession - keep it
// narrow and loud so it is not quietly extended to a wildcard.
if (csp.includes("script-src") && csp.includes("script-src *")) {
  problems.push("CSP script-src must not be a wildcard");
}

if (problems.length) {
  console.error("security header policy FAILED:");
  for (const p of problems) console.error("  -", p);
  process.exit(1);
}

console.log(`security header policy OK (${securityHeaders.length} headers, CSP verified)`);
