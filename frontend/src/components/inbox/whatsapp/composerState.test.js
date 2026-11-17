import { describe, expect, test } from "vitest";
import { composerAvailability, enterSends, lengthWarning, MAX_LENGTH, rowsFor, sendable } from "./composerState";

const NOW = new Date("2026-11-17T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600000).toISOString();

describe("composerAvailability", () => {
  test("allows typing inside the window", () => {
    expect(composerAvailability({ lastCustomerMessageAt: ago(1), now: NOW })).toMatchObject({ canType: true, reason: null });
  });
  test("closes the bar once the 24 hours have passed", () => {
    expect(composerAvailability({ lastCustomerMessageAt: ago(25), now: NOW })).toMatchObject({ canType: false, reason: "closed" });
    expect(composerAvailability({ lastCustomerMessageAt: ago(24), now: NOW }).canType).toBe(false);
    expect(composerAvailability({ lastCustomerMessageAt: ago(23.9), now: NOW }).canType).toBe(true);
  });
  test("a customer who never wrote is not blocked by the window", () => {
    expect(composerAvailability({ lastCustomerMessageAt: null, now: NOW }).canType).toBe(true);
  });
  test("pauses while a send is in flight, but not as a closed window", () => {
    expect(composerAvailability({ lastCustomerMessageAt: ago(1), sending: true, now: NOW })).toMatchObject({ canType: false, reason: "sending" });
    expect(composerAvailability({ lastCustomerMessageAt: ago(30), sending: true, now: NOW }).reason).toBe("closed");
  });
});

describe("enterSends", () => {
  test("plain Enter sends", () => expect(enterSends({ key: "Enter" })).toBe(true));
  test("Shift+Enter makes a new line", () => expect(enterSends({ key: "Enter", shiftKey: true })).toBe(false));
  test("Enter that confirms an IME candidate does not send", () => {
    expect(enterSends({ key: "Enter", isComposing: true })).toBe(false);
    expect(enterSends({ key: "Enter", nativeEvent: { isComposing: true } })).toBe(false);
    expect(enterSends({ key: "Enter", keyCode: 229 })).toBe(false);
  });
  test("other keys never send", () => expect(enterSends({ key: "a" })).toBe(false));
});

describe("rowsFor", () => {
  test("grows with lines up to five", () => {
    expect(rowsFor("")).toBe(1);
    expect(rowsFor("one")).toBe(1);
    expect(rowsFor("a\nb")).toBe(2);
    expect(rowsFor("1\n2\n3\n4\n5\n6\n7")).toBe(5);
    expect(rowsFor(null)).toBe(1);
  });
});

describe("sendable and lengthWarning", () => {
  test("rejects blank and over-long text", () => {
    expect(sendable("hi")).toBe(true);
    expect(sendable("   \n ")).toBe(false);
    expect(sendable("")).toBe(false);
    expect(sendable("a".repeat(MAX_LENGTH))).toBe(true);
    expect(sendable("a".repeat(MAX_LENGTH + 1))).toBe(false);
  });
  test("warns only near the limit", () => {
    expect(lengthWarning("short")).toBeNull();
    expect(lengthWarning("a".repeat(3700))).toMatchObject({ left: MAX_LENGTH - 3700, over: false });
    expect(lengthWarning("a".repeat(MAX_LENGTH + 5))).toMatchObject({ over: true, left: -5 });
  });
});
