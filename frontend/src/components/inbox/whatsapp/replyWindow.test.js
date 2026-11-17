import { describe, expect, test } from "vitest";
import { formatLeft, headerSubtitle, replyWindow } from "./replyWindow";

const NOW = new Date("2026-11-17T12:00:00Z");
const ago = (h, m = 0) => new Date(NOW.getTime() - (h * 60 + m) * 60000).toISOString();

describe("replyWindow", () => {
  test("is open for a customer who wrote recently", () => {
    const w = replyWindow(ago(1), NOW);
    expect(w.state).toBe("open");
    expect(w.msLeft).toBe(23 * 3600 * 1000);
  });
  test("is closing in the last two hours", () => {
    expect(replyWindow(ago(22, 30), NOW).state).toBe("closing");
    expect(replyWindow(ago(22), NOW).state).toBe("closing");
    expect(replyWindow(ago(21, 59), NOW).state).toBe("open");
  });
  test("closes at exactly 24 hours", () => {
    expect(replyWindow(ago(24), NOW).state).toBe("closed");
    expect(replyWindow(ago(23, 59), NOW).state).toBe("closing");
    expect(replyWindow(ago(30), NOW).msLeft).toBe(0);
  });
  test("has no window to speak of when the customer never wrote or the date is bad", () => {
    expect(replyWindow(null, NOW).state).toBe("never");
    expect(replyWindow(undefined, NOW).state).toBe("never");
    expect(replyWindow("not a date", NOW).state).toBe("never");
  });
});

describe("formatLeft", () => {
  test("reads naturally in English and Arabic", () => {
    expect(formatLeft((5 * 60 + 20) * 60000)).toBe("5h 20m");
    expect(formatLeft(45 * 60000)).toBe("45m");
    expect(formatLeft(2 * 3600000)).toBe("2h");
    expect(formatLeft(30000)).toBe("under a minute");
    expect(formatLeft((5 * 60 + 20) * 60000, "ar")).toBe("5 س 20 د");
    expect(formatLeft(-5)).toBe("under a minute");
  });
});

describe("headerSubtitle", () => {
  const sub = (phone, at, lang) => headerSubtitle({ phone, windowInfo: replyWindow(at, NOW), lang });
  test("shows just the number while the window is comfortably open", () => {
    expect(sub("+20 100 123 4567", ago(1))).toBe("+20 100 123 4567");
  });
  test("warns when the window is about to close", () => {
    expect(sub("+20 100 123 4567", ago(22, 30))).toBe("+20 100 123 4567 · Reply window ends in 1h 30m");
  });
  test("says plainly when the window has closed", () => {
    expect(sub("+20 100 123 4567", ago(30))).toBe("+20 100 123 4567 · Reply window closed");
    expect(sub("", ago(30), "ar")).toBe("انتهت نافذة الرد");
  });
  test("never invents a number and says nothing about a customer who never wrote", () => {
    expect(sub("", null)).toBe("");
  });
});
