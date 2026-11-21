// @vitest-environment node
import { describe, expect, it } from "vitest";

/**
 * FB.login answers through its callback the moment the Facebook window is closed or refused. The
 * WhatsApp connect used to ignore that answer when it carried no code and keep the button on
 * "Connecting…" for the full 10 minute signup timeout, while Facebook, Messenger and Instagram free
 * the button within a second of the window closing. A window that stops on a message from Meta
 * ("can't onboard customers right now") looked exactly like a page that was still working.
 */
describe("whatsappLoginOutcome", () => {
  it("hands over the authorization code when Facebook returned one", async () => {
    const { whatsappLoginOutcome } = await import("./ChannelsSettings.jsx");
    expect(whatsappLoginOutcome({ authResponse: { code: "abc" } }, true)).toEqual({ code: "abc" });
  });

  it.each([
    ["the window was closed", { authResponse: null, status: "unknown" }],
    ["the owner refused", { status: "not_authorized" }],
    ["no answer object at all", undefined],
    ["an empty code", { authResponse: { code: "" } }],
  ])("frees the button at once when %s, with a reason the owner can act on", async (_n, response) => {
    const { whatsappLoginOutcome } = await import("./ChannelsSettings.jsx");
    for (const isAr of [true, false]) {
      const out = whatsappLoginOutcome(response, isAr);
      expect(out.code).toBeUndefined();
      expect(out.error).toBeInstanceOf(Error);
      expect(out.error.message.length).toBeGreaterThan(20);
    }
  });

  it("tells the owner a stuck Meta message is the Meta app's setup, not this page", async () => {
    const { whatsappLoginOutcome } = await import("./ChannelsSettings.jsx");
    expect(whatsappLoginOutcome(undefined, false).error.message).toMatch(/can't onboard customers/i);
    expect(whatsappLoginOutcome(undefined, true).error.message).toMatch(/تأهيل العملاء/);
  });
});

describe("connectingHint", () => {
  it("says nothing while the connect is young, then points at the Meta app once it has run long", async () => {
    const { connectingHint } = await import("./ChannelsSettings.jsx");
    expect(connectingHint(5_000, "whatsapp", false)).toBe("");
    const late = connectingHint(60_000, "whatsapp", false);
    expect(late).toMatch(/Meta/);
    expect(late).toMatch(/can't onboard customers/i);
    expect(connectingHint(60_000, "whatsapp", true)).toMatch(/تأهيل العملاء/);
  });

  it("only speaks for WhatsApp, whose window gives no signal while it sits on a Meta message", async () => {
    const { connectingHint } = await import("./ChannelsSettings.jsx");
    for (const id of ["facebook", "messenger", "instagram"]) expect(connectingHint(600_000, id, false)).toBe("");
  });
});
