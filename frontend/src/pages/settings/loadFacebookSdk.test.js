// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

/**
 * loadFacebookSdk rejects from script.onerror. That branch read `isAr`, which only exists inside the
 * component, so an ad blocker turned the friendly message into a ReferenceError.
 */
function stubBrowserWhereTheScriptFails() {
  const script = {};
  vi.stubGlobal("window", {});
  vi.stubGlobal("document", {
    createElement: () => script,
    body: { appendChild: () => script.onerror() },
  });
}

describe("loadFacebookSdk when the script cannot load", () => {
  it.each([
    [true, /Facebook SDK/],
    [false, /Could not load the Facebook SDK/],
  ])("rejects with a readable message (isAr=%s), not a ReferenceError", async (isAr, pattern) => {
    stubBrowserWhereTheScriptFails();
    const { loadFacebookSdk } = await import("./ChannelsSettings.jsx");
    const err = await loadFacebookSdk("app", "v27.0", isAr).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).not.toBe("ReferenceError");
    expect(err.message).toMatch(pattern);
  }, 15000);
});

describe("Meta SDK event origins", () => {
  it("accepts Meta-owned HTTPS hosts", async () => {
    const { isMetaSdkOrigin } = await import("./ChannelsSettings.jsx");
    expect(isMetaSdkOrigin("https://www.facebook.com")).toBe(true);
    expect(isMetaSdkOrigin("https://business.facebook.com")).toBe(true);
  });

  it("rejects lookalike domains and insecure origins", async () => {
    const { isMetaSdkOrigin } = await import("./ChannelsSettings.jsx");
    expect(isMetaSdkOrigin("https://evilfacebook.com")).toBe(false);
    expect(isMetaSdkOrigin("https://facebook.com.evil.test")).toBe(false);
    expect(isMetaSdkOrigin("http://facebook.com")).toBe(false);
    expect(isMetaSdkOrigin("not a URL")).toBe(false);
  });

  it("requires the same origin and the exact OAuth popup window", async () => {
    const { isMetaOAuthPopupMessage } = await import("./ChannelsSettings.jsx");
    const popup = {};
    const origin = "https://fihrist.world";
    expect(isMetaOAuthPopupMessage({ origin, source: popup }, popup, origin)).toBe(true);
    expect(isMetaOAuthPopupMessage({ origin: "https://evil.test", source: popup }, popup, origin)).toBe(false);
    expect(isMetaOAuthPopupMessage({ origin, source: {} }, popup, origin)).toBe(false);
  });
});

describe("WhatsApp Embedded Signup v5", () => {
  it("maps the v5 messaging account and phone ids to the backend contract", async () => {
    const { extractWhatsAppSignupIds } = await import("./ChannelsSettings.jsx");
    expect(
      extractWhatsAppSignupIds({
        messaging_account_ids: ["waba-123"],
        phone_number_id: "phone-456",
        business_id: "business-789",
      })
    ).toEqual({ wabaId: "waba-123", phoneNumberId: "phone-456" });
  });

  it("continues accepting legacy session names during Meta's flow migration", async () => {
    const { extractWhatsAppSignupIds } = await import("./ChannelsSettings.jsx");
    expect(extractWhatsAppSignupIds({ waba_id: 123, phone_number_id: 456 })).toEqual({
      wabaId: "123",
      phoneNumberId: "456",
    });
  });
});
