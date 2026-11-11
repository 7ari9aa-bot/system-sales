import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The sign-in screens depend on two things that can be checked without a DOM:
//   1. the server's `captcha_required` answer reaches the screen as err.code
//      (that is what makes the widget appear), and
//   2. a token is sent ONLY when there is one, so the body every existing client
//      (the desktop app included) sends today stays byte for byte the same.
let cookie = "";
beforeEach(() => {
  cookie = "csrf_token=abc123";
  vi.stubGlobal("document", {
    get cookie() { return cookie; },
    set cookie(v) { cookie = v; },
  });
  vi.stubGlobal("window", { location: { origin: "http://localhost" } });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });

describe("captcha_required reaches the screen", () => {
  it("surfaces the server's code on the ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        reply(400, { error: { code: "captcha_required", message: "Please complete the verification challenge and try again." } }),
      ),
    );
    const { publicApi } = await import("./api.js");
    await expect(publicApi("/auth/password-reset/request", { body: { email: "a@b.co" } })).rejects.toMatchObject({
      code: "captcha_required",
    });
  });
});

describe("the request body stays unchanged unless a token exists", () => {
  it("publicApi sends exactly what it is given", async () => {
    const seen = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url, init) => {
        seen.push(JSON.parse(init.body));
        return reply(202, { message: "ok" });
      }),
    );
    const { publicApi } = await import("./api.js");
    await publicApi("/auth/resend-verification", { body: { email: "a@b.co" } });
    await publicApi("/auth/resend-verification", { body: { email: "a@b.co", captcha_token: "tok" } });
    expect(seen[0]).toEqual({ email: "a@b.co" });
    expect("captcha_token" in seen[0]).toBe(false);
    expect(seen[1]).toEqual({ email: "a@b.co", captcha_token: "tok" });
  });
});

describe("the widget component is inert without a site key", () => {
  it("reports itself disabled and renders nothing", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "");
    const mod = await import("../components/Turnstile.jsx");
    expect(mod.turnstileEnabled()).toBe(false);
    expect(mod.TURNSTILE_SITE_KEY).toBe("");
    // The screens gate their submit button on turnstileEnabled(), so a false here is what
    // keeps sign-in usable before the keys exist.
  });

  it("is enabled when a site key is present", async () => {
    vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "1x00000000000000000000AA");
    vi.resetModules();
    const mod = await import("../components/Turnstile.jsx");
    expect(mod.turnstileEnabled()).toBe(true);
  });
});
