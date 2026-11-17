import { describe, expect, test } from "vitest";
import { TYPING_REFRESH_MS, readSignalBody, shouldSignalTyping, supportsReadSignal } from "./readSignal";

const NOW = Date.parse("2026-11-17T12:00:00Z");
const recent = new Date(NOW - 3600 * 1000).toISOString();
const old = new Date(NOW - 25 * 3600 * 1000).toISOString();
const base = { text: "hi", lastSentAt: null, now: NOW, lastCustomerMessageAt: recent };

describe("typing signal", () => {
  test("sends the first time someone types in an open window", () => {
    expect(shouldSignalTyping(base)).toBe(true);
  });
  test("an empty or blank box is not typing", () => {
    expect(shouldSignalTyping({ ...base, text: "" })).toBe(false);
    expect(shouldSignalTyping({ ...base, text: "   " })).toBe(false);
  });
  test("is throttled: nothing again within 20 seconds, then it refreshes", () => {
    expect(shouldSignalTyping({ ...base, lastSentAt: NOW - 5000 })).toBe(false);
    expect(shouldSignalTyping({ ...base, lastSentAt: NOW - TYPING_REFRESH_MS + 1 })).toBe(false);
    expect(shouldSignalTyping({ ...base, lastSentAt: NOW - TYPING_REFRESH_MS })).toBe(true);
  });
  test("the refresh is sooner than Meta's 25 second expiry", () => {
    expect(TYPING_REFRESH_MS).toBeLessThan(25000);
  });
  test("nothing once the 24h window is closed, or if the customer never wrote", () => {
    expect(shouldSignalTyping({ ...base, lastCustomerMessageAt: old })).toBe(false);
    expect(shouldSignalTyping({ ...base, lastCustomerMessageAt: null })).toBe(false);
  });
});

describe("read signal", () => {
  test("body carries only the typing flag", () => {
    expect(readSignalBody(true)).toEqual({ typing: true });
    expect(readSignalBody(false)).toEqual({ typing: false });
    expect(readSignalBody(undefined)).toEqual({ typing: false });
  });
  test("only WhatsApp chats with an id", () => {
    expect(supportsReadSignal({ id: "1", channel: "whatsapp" })).toBe(true);
    expect(supportsReadSignal({ id: "1", channelId: "whatsapp" })).toBe(true);
    expect(supportsReadSignal({ id: "1", channel: "telegram" })).toBe(false);
    expect(supportsReadSignal({ channel: "whatsapp" })).toBe(false);
    expect(supportsReadSignal(null)).toBe(false);
  });
});
