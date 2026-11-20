import { afterEach, describe, expect, it } from "vitest";
import { currencySign, fmtMoney, fmtMoneyOrDash, setShopCurrency } from "./format";

afterEach(() => setShopCurrency(undefined));

describe("amounts follow the shop's own currency", () => {
  it("is the Egyptian pound until a shop says otherwise", () => {
    expect(fmtMoney(12.5)).toBe("12.50 ج.م");
    expect(currencySign()).toBe("ج.م");
  });

  it("writes every amount in the currency the shop trades in", () => {
    setShopCurrency("SAR");
    expect(fmtMoney(12.5)).not.toMatch(/ج\.م/);
    expect(fmtMoney(12.5)).toMatch(/^12\.50 /);
    expect(fmtMoneyOrDash(3)).toMatch(/^3\.00 /);
    expect(fmtMoneyOrDash(null)).toBe("—");
  });

  it("goes back to the pound for a shop with no currency or one it cannot read", () => {
    setShopCurrency("SAR");
    for (const bad of [undefined, null, "", "x", 5, "EGPX"]) {
      setShopCurrency(bad);
      expect(currencySign(), String(bad)).toBe("ج.م");
    }
  });

  it("a second shop replaces the first one's currency, never mixes", () => {
    setShopCurrency("SAR");
    const sar = fmtMoney(1);
    setShopCurrency("EGP");
    expect(fmtMoney(1)).toBe("1.00 ج.م");
    expect(sar).not.toBe(fmtMoney(1));
  });
});
