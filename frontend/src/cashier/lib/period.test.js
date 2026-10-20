import { describe, expect, it } from "vitest";
import { inShopPeriod, shopToday } from "./period";

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

describe("shopToday is the Cairo calendar day, not the UTC day", () => {
  it("00:30 in Cairo (still yesterday in UTC) is already the NEW day", () => {
    // Cairo is UTC+2 in winter: 22:30Z on the 20th is 00:30 on the 21st.
    expect(shopToday(new Date("2026-01-20T22:30:00Z"))).toBe("2026-01-21");
    expect(new Date("2026-01-20T22:30:00Z").toISOString().slice(0, 10)).toBe("2026-01-20"); // the old, wrong answer
  });
  it("00:30 in Cairo in summer time (UTC+3)", () => {
    expect(shopToday(new Date("2026-07-20T21:30:00Z"))).toBe("2026-07-21");
  });
  it("midday is the same day in both", () => expect(shopToday(new Date("2026-10-20T10:00:00Z"))).toBe("2026-10-20"));
  it("just before local midnight is still the same day", () => expect(shopToday(new Date("2026-01-20T21:59:00Z"))).toBe("2026-01-20"));
  it("the zone can be overridden", () => expect(shopToday(new Date("2026-01-20T22:30:00Z"), "UTC")).toBe("2026-01-20"));
});
