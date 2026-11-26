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
