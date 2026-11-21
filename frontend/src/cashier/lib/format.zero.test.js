import { afterEach, describe, expect, it } from "vitest";
import { fmtInt, fmtMoney, fmtMoneyOrDash, fmtMoneyShort, fmtNumber, setShopCurrency } from "./format";

afterEach(() => setShopCurrency(undefined));

// A figure that rounds to nothing must read as nothing. JavaScript keeps the minus on -0.004 after
// rounding, and on a literal -0, so a profit screen showed "-0.00 ج.م" for a shop that broke even.
describe("a figure that rounds to zero carries no minus sign", () => {
  it("money", () => {
    for (const v of [-0.004, -0.0049, -0, 0, 0.004, "-0.001", -1e-9]) {
      expect(fmtMoney(v), String(v)).toBe("0.00 ج.م");
    }
  });

  it("numbers at any precision", () => {
    expect(fmtNumber(-0.004)).toBe("0.00");
    expect(fmtNumber(-0.04, 1)).toBe("0.0");
    expect(fmtNumber(-0.4, 0)).toBe("0");
    expect(fmtNumber(-0, 3)).toBe("0.000");
  });

  it("whole figures", () => {
    expect(fmtMoneyShort(-0.4)).toBe("0");
    expect(fmtMoneyShort(-0)).toBe("0");
    expect(fmtInt(-0)).toBe("0");
    // a literal -0 is already turned into 0 by `|| 0`; it is a tiny negative that keeps the sign
    expect(fmtInt(-0.0001)).toBe("0");
  });

  it("keeps the shop's own currency sign", () => {
    setShopCurrency("SAR");
    expect(fmtMoney(-0.004)).toMatch(/^0\.00 /);
    expect(fmtMoney(-0.004)).not.toMatch(/-/);
  });

  it("an unknown amount is still a dash, never a zero", () => {
    expect(fmtMoneyOrDash(null)).toBe("—");
    expect(fmtMoneyOrDash(undefined)).toBe("—");
  });
});

// And a real loss still shows as a loss: the fix must only touch what rounds to nothing.
describe("real negatives and ordinary figures are unchanged", () => {
  it("a loss keeps its sign, grouping and cents", () => {
    expect(fmtMoney(-0.005)).toBe("-0.01 ج.م");
    expect(fmtMoney(-0.01)).toBe("-0.01 ج.م");
    expect(fmtMoney(-1234.5)).toBe("-1,234.50 ج.م");
    expect(fmtMoney(-1000000)).toBe("-1,000,000.00 ج.م");
  });

  it("positive and plain figures", () => {
    expect(fmtMoney(0)).toBe("0.00 ج.م");
    expect(fmtMoney(12.5)).toBe("12.50 ج.م");
    expect(fmtMoney(1234567.891)).toBe("1,234,567.89 ج.م");
    expect(fmtNumber(1234.5678, 1)).toBe("1,234.6");
    expect(fmtNumber(-2.5, 0)).toBe("-3");
    expect(fmtMoneyShort(-1234.5)).toBe("-1,235");
    expect(fmtInt(-12345)).toBe("-12,345");
    expect(fmtInt(12345)).toBe("12,345");
  });

  it("non-numbers still read as zero, as before", () => {
    expect(fmtMoney("abc")).toBe("0.00 ج.م");
    expect(fmtMoney(undefined)).toBe("0.00 ج.م");
    expect(fmtNumber(null)).toBe("0.00");
    expect(fmtInt("x")).toBe("0");
  });
});
