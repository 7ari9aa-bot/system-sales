import { describe, expect, it } from "vitest";
import { createVercelConfig } from "../../vercel.mjs";

/**
 * The backend answers its liveness probes at the root (/healthz, /readyz), so the
 * frontend has to hand those two paths to it. Before this, fihrist.world/readyz
 * returned the SPA's 404 and every uptime check reported the site as down.
 */
describe("vercel probe routing", () => {
  const config = createVercelConfig({ environment: "production" });
  const rewrites = config.rewrites ?? [];
  const find = (source) => rewrites.find((r) => r.source === source);

  it("proxies /readyz and /healthz to the backend root", () => {
    for (const path of ["/readyz", "/healthz"]) {
      const rule = find(path);
      expect(rule, `${path} has no rewrite`).toBeTruthy();
      expect(rule.destination).toMatch(/\/readyz$|\/healthz$/);
      expect(rule.destination).not.toContain("/api/v1");
    }
  });

  it("keeps the API prefix on the API rewrites", () => {
    expect(find("/api/v1/:path*")?.destination).toContain("/api/v1/:path*");
  });

  it("leaves a preview build without any backend rewrite", () => {
    const preview = createVercelConfig({ environment: "preview" });
    const sources = (preview.rewrites ?? []).map((r) => r.source);
    expect(sources).not.toContain("/readyz");
    expect(sources).not.toContain("/api/v1/:path*");
  });
});

/**
 * The voice call streams PCM over a websocket to the API. Vercel proxies HTTP
 * rewrites but does not upgrade websockets, so the socket targets the API origin
 * directly — and the browser refuses it unless connect-src names that origin.
 * Measured on production: the call created a session (201), minted a ticket (200),
 * and then nothing reached the server, because this directive blocked it.
 */
describe("content security policy for the voice socket", () => {
  const csp = createVercelConfig({ environment: "production" })
    .headers[0].headers.find((h) => h.key === "Content-Security-Policy").value;
  const connectSrc = csp.match(/connect-src ([^;]+)/)[1].split(/\s+/);

  it("allows the API websocket origin the call actually opens", () => {
    expect(connectSrc).toContain("wss://p01--system-sales--smkyc4wjfbtq.code.run");
  });

  it("still keeps the REST API same-origin and Meta's own hosts", () => {
    expect(connectSrc).toContain("'self'");
    expect(connectSrc).toContain("https://graph.facebook.com");
    expect(connectSrc).not.toContain("ws:");
  });

  it("names no websocket origin when the deployment has no backend", () => {
    const preview = createVercelConfig({ environment: "preview" })
      .headers[0].headers.find((h) => h.key === "Content-Security-Policy").value;
    expect(preview).not.toContain("wss://");
  });
});
