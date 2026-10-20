import { describe, expect, it } from "vitest";
import {
  addMoney,
  fromMinor,
  isWireMoney,
  mulMoney,
  parseMoney,
  splitEvenly,
  subMoney,
  sumMoney,
  toMinor,
  toWire,
} from "./money";

// Backend contract (orders/money.py + pos/router.py _MONEY):
//   wire = string matching ^\d+(\.\d{1,2})?$ ; rounding = ROUND_HALF_UP to 2 places.

describe("wire format", () => {
  it("accepts what the backend accepts", () => {
    for (const ok of ["0", "10", "10.5", "10.50", "0.01", "1234567.89"]) {
      expect(isWireMoney(ok)).toBe(true);
    }
  });
  it("rejects what the backend rejects", () => {
    for (const bad of ["", "-1", "1.005", "1,5", " 1", "1 ", "abc", "1e3", ".5", "5.", null, undefined, 10]) {
      expect(isWireMoney(bad)).toBe(false);
    }
  });
});

describe("toMinor / fromMinor (integer cents, never float)", () => {
  it("round-trips exactly", () => {
    expect(toMinor("10.50")).toBe(1050);
    expect(toMinor("0.01")).toBe(1);
    expect(toMinor("10")).toBe(1000);
    expect(fromMinor(1050)).toBe("10.50");
    expect(fromMinor(1)).toBe("0.01");
    expect(fromMinor(0)).toBe("0.00");
  });
  it("accepts numbers from the UI and rounds HALF_UP", () => {
    expect(toMinor(10.5)).toBe(1050);
    expect(toMinor(1.005)).toBe(101); // float 1.005 is 1.00499999...; HALF_UP on the decimal text must still give 1.01
    expect(toMinor(2.675)).toBe(268);
    expect(toMinor(0.004)).toBe(0);
    expect(toMinor(0.005)).toBe(1);
  });
  it("accepts typed strings with more than 2 decimals by rounding, not by failing silently", () => {
    expect(toMinor("3.3333")).toBe(333);
    expect(toMinor("3.335")).toBe(334);
  });
  it("throws on garbage instead of returning NaN", () => {
    expect(() => toMinor("abc")).toThrow();
    expect(() => toMinor(NaN)).toThrow();
    expect(() => toMinor(Infinity)).toThrow();
    expect(() => toMinor(null)).toThrow();
  });
});

describe("toWire", () => {
  it("always yields a backend-valid string", () => {
    expect(toWire(10)).toBe("10.00");
    expect(toWire("10.5")).toBe("10.50");
    expect(toWire(0.1 + 0.2)).toBe("0.30");
    expect(isWireMoney(toWire(99.999))).toBe(true);
  });
  it("refuses negatives (the wire is non-negative; direction is a separate field)", () => {
    expect(() => toWire(-1)).toThrow(/negative/i);
  });
});

describe("arithmetic has no float drift", () => {
  it("0.1 + 0.2 is exactly 0.30", () => {
    expect(addMoney("0.10", "0.20")).toBe("0.30");
  });
  it("sum of many small amounts is exact", () => {
    const parts = Array.from({ length: 1000 }, () => "0.10");
    expect(sumMoney(parts)).toBe("100.00");
  });
  it("subtraction may go negative internally and reports it", () => {
    expect(subMoney("5.00", "7.50")).toBe("-2.50");
    expect(parseMoney(subMoney("5.00", "7.50")).minor).toBe(-250);
  });
  it("quantity x unit price rounds HALF_UP once, on the line total", () => {
    expect(mulMoney("19.99", 3)).toBe("59.97");
    expect(mulMoney("0.335", 1)).toBe("0.34");
    expect(mulMoney("10.00", 0)).toBe("0.00");
  });
});

describe("the bugs that cost real money in the backend (orders/money.py)", () => {
  it("three refunds of 3.3333 are three cents-rounded values that sum to 9.99, not 9.9999", () => {
    const each = fromMinor(toMinor("3.3333"));
    expect(each).toBe("3.33");
    expect(sumMoney([each, each, each])).toBe("9.99");
  });
  it("0.001 becomes 0.00 and is detectable as zero (never a silent 'refund of nothing')", () => {
    expect(toMinor("0.001")).toBe(0);
  });
});

describe("splitEvenly (split tenders / discounts): parts always sum to the whole", () => {
  it("100.00 into 3 = 33.34 + 33.33 + 33.33", () => {
    const parts = splitEvenly("100.00", 3);
    expect(parts).toEqual(["33.34", "33.33", "33.33"]);
    expect(sumMoney(parts)).toBe("100.00");
  });
  it("never loses a cent for any n", () => {
    for (let n = 1; n <= 17; n++) {
      for (const total of ["0.01", "1.00", "99.99", "1234.56"]) {
        expect(sumMoney(splitEvenly(total, n))).toBe(total);
      }
    }
  });
});
