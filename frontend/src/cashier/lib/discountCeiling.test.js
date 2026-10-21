import { describe, expect, it } from "vitest";
import { ceilingPct, parseCeilingInput } from "./discountCeiling";

describe("ceilingPct (what the till screen allows)", () => {
  it("reads the profile's server value", () => {
    expect(ceilingPct({ discount_ceiling_pct: "5.00" })).toBe(5);
    expect(ceilingPct({ discount_ceiling_pct: "0.00" })).toBe(0);
    expect(ceilingPct({ discount_ceiling_pct: "100.00" })).toBe(100);
  });
  it("no profile or a broken value means no discount without a manager, never the old fake 20", () => {
    expect(ceilingPct(null)).toBe(0);
    expect(ceilingPct(undefined)).toBe(0);
    expect(ceilingPct({})).toBe(0);
    expect(ceilingPct({ discount_ceiling_pct: "abc" })).toBe(0);
    expect(ceilingPct({ discount_ceiling_pct: "-3" })).toBe(0);
  });
  it("never reports above 100", () => {
    expect(ceilingPct({ discount_ceiling_pct: "250" })).toBe(100);
  });
});

describe("parseCeilingInput (what the settings box may send)", () => {
  it("accepts 0 to 100 with up to 2 decimals and normalizes to 2 decimals", () => {
    expect(parseCeilingInput("5")).toEqual({ ok: true, value: "5.00" });
    expect(parseCeilingInput(" 7.5 ")).toEqual({ ok: true, value: "7.50" });
    expect(parseCeilingInput("0")).toEqual({ ok: true, value: "0.00" });
    expect(parseCeilingInput("100")).toEqual({ ok: true, value: "100.00" });
  });
  it("rejects empty, negative, over 100, 3 decimals, exponent and non-latin digits", () => {
    for (const bad of ["", "  ", "-1", "101", "100.01", "5.123", "1e1", "٥", "abc", null, undefined]) {
      expect(parseCeilingInput(bad).ok).toBe(false);
    }
  });
});
