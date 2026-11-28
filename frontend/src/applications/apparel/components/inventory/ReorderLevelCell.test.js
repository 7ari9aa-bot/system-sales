import { describe, expect, it } from "vitest";
import { levelErrorMessage, parseLevel } from "./ReorderLevelCell";

describe("parseLevel", () => {
  it("accepts a whole number from zero up, trimmed", () => {
    expect(parseLevel("0")).toBe(0);
    expect(parseLevel(" 12 ")).toBe(12);
    expect(parseLevel("1000000")).toBe(1_000_000);
  });
  it("rejects everything that is not a plain whole number", () => {
    for (const bad of ["", "  ", "-1", "2.5", "1e3", "abc", "1,000", "٣", "1000001", "99999999", null, undefined]) {
      expect(parseLevel(bad)).toBeNull();
    }
  });
});

describe("levelErrorMessage", () => {
  it("tells a refused cashier the edit is for managers", () => {
    expect(levelErrorMessage({ status: 403 })).toMatch(/للمدير أو المالك/);
  });
  it("has a safe default for anything else", () => {
    expect(levelErrorMessage({ status: 500 })).toMatch(/تعذّر/);
    expect(levelErrorMessage(undefined)).toMatch(/تعذّر/);
  });
});
