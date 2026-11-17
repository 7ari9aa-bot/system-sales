import { describe, expect, test } from "vitest";
import { distanceFromBottom, isAwayFromBottom, unreadSince } from "./scrollState";

describe("distanceFromBottom", () => {
  test("is zero at the bottom and never negative", () => {
    expect(distanceFromBottom({ scrollHeight: 1000, scrollTop: 600, clientHeight: 400 })).toBe(0);
    expect(distanceFromBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 400 })).toBe(0);
  });
  test("measures the gap", () => {
    expect(distanceFromBottom({ scrollHeight: 2000, scrollTop: 0, clientHeight: 500 })).toBe(1500);
  });
});

describe("isAwayFromBottom", () => {
  test("a small gap is still following", () => {
    expect(isAwayFromBottom({ scrollHeight: 1000, scrollTop: 400, clientHeight: 400 })).toBe(false);
  });
  test("a large gap is reading history", () => {
    expect(isAwayFromBottom({ scrollHeight: 3000, scrollTop: 0, clientHeight: 500 })).toBe(true);
  });
});

describe("unreadSince", () => {
  const msgs = [
    { id: "a", side: "in" },
    { id: "b", side: "out" },
    { id: "c", side: "in" },
    { id: "d", side: "in", senderType: "system" },
    { id: "e", side: "in" },
  ];
  test("counts only customer messages after the last one seen", () => {
    expect(unreadSince(msgs, "a")).toBe(2);
  });
  test("nothing new after the newest", () => {
    expect(unreadSince(msgs, "e")).toBe(0);
  });
  test("an unknown or missing marker counts nothing rather than everything", () => {
    expect(unreadSince(msgs, "zzz")).toBe(0);
    expect(unreadSince(msgs, null)).toBe(0);
    expect(unreadSince(undefined, "a")).toBe(0);
  });
});
