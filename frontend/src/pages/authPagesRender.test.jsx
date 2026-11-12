// @vitest-environment node
import React from "react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// Server rendering has no browser. Stub only what these pages read while rendering, so the test
// needs no DOM library; anything ELSE undefined still throws, which is the point.
const store = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() };
};
{
  vi.stubGlobal("localStorage", store());
  vi.stubGlobal("sessionStorage", store());
  vi.stubGlobal("window", {
    location: { href: "http://t/x", search: "?token=t", pathname: "/x", origin: "http://t", hash: "" },
    localStorage,
    sessionStorage,
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener() {},
    removeEventListener() {},
  });
  vi.stubGlobal("document", { documentElement: { lang: "ar", dir: "rtl", classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {} }, cookie: "", title: "" });
  vi.stubGlobal("navigator", { language: "ar", languages: ["ar"] });
}

const { LanguageProvider } = await import("@/lib/marketing-i18n");
const { AuthProvider } = await import("@/lib/AuthContext");
const { default: ForgotPassword } = await import("./ForgotPassword");
const { default: Login } = await import("./Login");
const { default: Register } = await import("./Register");
const { default: VerifyEmail } = await import("./VerifyEmail");

/**
 * Every public auth page must at least RENDER. The Turnstile change shipped ForgotPassword and
 * VerifyEmail using `captchaToken` / `captchaReset` that nothing declared; the pages threw a
 * ReferenceError on first render and a source-level contract test could not see it.
 */
const pages = { ForgotPassword, Login, Register, VerifyEmail };

describe.each(Object.entries(pages))("%s", (name, Page) => {
  it("renders without throwing", () => {
    const html = renderToString(
      <LanguageProvider>
        <MemoryRouter initialEntries={["/x?token=t&email=a%40b.test"]}>
          <AuthProvider>
            <Page />
          </AuthProvider>
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(html.length, `${name} rendered nothing`).toBeGreaterThan(200);
  });
});
