import { describe, expect, it } from "vitest";
import { inShopPeriod } from "./period";

const NOW = new Date("2026-10-20T11:00:00Z"); // 14:00 Cairo (UTC+3 on this date)

describe("inShopPeriod", () => {
  it("today includes a shift opened earlier today and excludes yesterday", () => {
    expect(inShopPeriod("2026-10-20T07:53:00Z", "today", NOW)).toBe(true);
    expect(inShopPeriod("2026-10-19T12:00:00Z", "today", NOW)).toBe(false);
  });
  it("uses the Cairo day: 00:30 Cairo on the 20th is 21:30 UTC on the 19th, still TODAY", () => {
    expect(inShopPeriod("2026-10-19T21:30:00Z", "today", NOW)).toBe(true);
  });
  it("and 23:30 Cairo on the 19th (20:30 UTC) is yesterday", () => {
    expect(inShopPeriod("2026-10-19T20:30:00Z", "today", NOW)).toBe(false);
  });
  it("7d is exactly 7 shop days: 6 days ago in, 7 days ago out", () => {
    expect(inShopPeriod("2026-10-14T10:00:00Z", "7d", NOW)).toBe(true);
    expect(inShopPeriod("2026-10-13T10:00:00Z", "7d", NOW)).toBe(false);
  });
  it("30d", () => {
    expect(inShopPeriod("2026-09-21T10:00:00Z", "30d", NOW)).toBe(true);
    expect(inShopPeriod("2026-09-20T10:00:00Z", "30d", NOW)).toBe(false);
  });
  it("never includes the future or garbage", () => {
    expect(inShopPeriod("2026-10-21T10:00:00Z", "30d", NOW)).toBe(false);
    expect(inShopPeriod("not a date", "7d", NOW)).toBe(false);
    expect(inShopPeriod(undefined, "7d", NOW)).toBe(false);
  });
  it("an unknown period falls back to 7 days", () => expect(inShopPeriod("2026-10-14T10:00:00Z", "weird", NOW)).toBe(true));
});
