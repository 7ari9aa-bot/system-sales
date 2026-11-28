import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";
import { fmtMoneyDeduction, setShopCurrency } from "./format";

afterEach(() => setShopCurrency(undefined));

// A return that rounds to nothing must not print a minus in front of it: the shifts table showed
// "−0.00 ج.م" in red for a day whose returns were a few piastres (or a rounded exchange line).
describe("an amount taken out of the drawer", () => {
  it("carries the minus sign when there is something to take", () => {
    expect(fmtMoneyDeduction(10)).toBe("−10.00 ج.م");
    expect(fmtMoneyDeduction(0.01)).toBe("−0.01 ج.م");
    expect(fmtMoneyDeduction(1234.5)).toBe("−1,234.50 ج.م");
  });

  it("rounds to nothing without a minus, whatever sign it arrives with", () => {
    for (const v of [0, -0, 0.004, -0.004, -0.0049, "0", "0.001", -1e-9]) {
      expect(fmtMoneyDeduction(v), String(v)).toBe("0.00 ج.م");
    }
  });

  it("never prints a double minus when the server already sent a negative", () => {
    expect(fmtMoneyDeduction(-10)).toBe("−10.00 ج.م");
    expect(fmtMoneyDeduction(-0.01)).toBe("−0.01 ج.م");
  });

  it("follows the shop's own currency sign", () => {
    setShopCurrency("SAR");
    expect(fmtMoneyDeduction(5)).toMatch(/^−5\.00 /);
    expect(fmtMoneyDeduction(5)).not.toMatch(/ج\.م/);
  });
});

// The four screens that print a return amount must use the guarded formatter. A bare
// `−${fmtMoney(...)}` in any of them brings "−0.00" back on a real screen.
describe("every return column is wired to the guarded formatter", () => {
  // The tree moved one level deeper: a path may be written from the application
  // root or from src, so resolve against both.
  const read = (rel) => {
    for (const base of ["../../../../", "../../../", "../../"]) {
      try {
        return readFileSync(new URL(base + rel, import.meta.url), "utf8");
      } catch {
        // try the next base
      }
    }
    throw new Error(`cannot resolve ${rel}`);
  };
  const screens = [
    "components/shifts/shiftColumns.jsx",
    "components/shifts/DayReport.jsx",
    "components/shifts/ShiftDetailsDialog.jsx",
    "components/reports/ZReportSection.jsx",
  ];

  for (const screen of screens) {
    it(`${screen} writes returns through fmtMoneyDeduction`, () => {
      const source = read(screen);
      expect(source).toMatch(/fmtMoneyDeduction/);
      expect(source).not.toMatch(/`−\$\{fmtMoney\(/);
    });
  }
});
