import { describe, expect, it } from "vitest";
import { buildSellPayload, cartItems, clampQty, settle } from "./checkout";

describe("clampQty (the backend quote does not check stock, so the screen must)", () => {
  it("never goes below 1 or above what is available", () => {
    expect(clampQty(0, 5)).toBe(1);
    expect(clampQty(-3, 5)).toBe(1);
    expect(clampQty(9, 5)).toBe(5);
    expect(clampQty("3", 5)).toBe(3);
    expect(clampQty("abc", 5)).toBe(1);
  });
  it("whole pieces only", () => expect(clampQty(2.7, 5)).toBe(2));
  it("a sold-out line cannot be raised at all", () => expect(clampQty(2, 0)).toBe(0));
});

describe("cartItems", () => {
  it("sends exactly variant + quantity (the server prices it, not the screen)", () => {
    expect(cartItems([{ variantId: "v1", qty: 2, price: 999 }])).toEqual([{ variant_id: "v1", quantity: 2 }]);
  });
});

describe("settle: tenders must equal the order total to the cent", () => {
  it("exact cash payment has no change", () => {
    expect(settle({ total: "42.50", tenders: [{ method: "cash", amount: "42.50" }] })).toMatchObject({ ok: true, change: "0.00", remaining: "0.00" });
  });
  it("cash over-tender becomes change and tenders are trimmed to the total", () => {
    const r = settle({ total: "42.50", tenders: [{ method: "cash", amount: "50" }] });
    expect(r).toMatchObject({ ok: true, change: "7.50", tenderedCash: "50.00" });
    expect(r.tenders).toEqual([{ method: "cash", amount: "42.50" }]);
  });
  it("split cash + card", () => {
    const r = settle({ total: "50.00", tenders: [{ method: "cash", amount: "30" }, { method: "card", amount: "20" }] });
    expect(r).toMatchObject({ ok: true, change: "0.00" });
    expect(r.tenders).toEqual([{ method: "cash", amount: "30.00" }, { method: "card", amount: "20.00" }]);
  });
  it("short payment is not ok and reports what is missing", () => {
    expect(settle({ total: "50.00", tenders: [{ method: "cash", amount: "30" }] })).toMatchObject({ ok: false, remaining: "20.00" });
  });
  it("being short by a single cent or by a single pound is still short (no tolerance)", () => {
    expect(settle({ total: "50.00", tenders: [{ method: "cash", amount: "49.99" }] })).toMatchObject({ ok: false, remaining: "0.01" });
    expect(settle({ total: "50.00", tenders: [{ method: "cash", amount: "49" }] })).toMatchObject({ ok: false, remaining: "1.00" });
    expect(settle({ total: "50.00", tenders: [{ method: "cash", amount: "50.00" }] }).ok).toBe(true);
  });
  it("card over the total is refused: only cash can produce change", () => {
    const r = settle({ total: "50.00", tenders: [{ method: "card", amount: "60" }] });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/card|بطاقة|non-cash/i);
  });
  it("cash + card where the card alone already covers the total: cash is the excess and is refused", () => {
    expect(settle({ total: "50.00", tenders: [{ method: "card", amount: "50" }, { method: "cash", amount: "10" }] }).ok).toBe(false);
  });
  it("ignores zero/blank rows and refuses negatives", () => {
    expect(settle({ total: "10.00", tenders: [{ method: "cash", amount: "10" }, { method: "card", amount: "0" }] }).tenders).toEqual([{ method: "cash", amount: "10.00" }]);
    expect(settle({ total: "10.00", tenders: [{ method: "cash", amount: "-5" }] }).ok).toBe(false);
  });
  it("cent precision: 0.1 + 0.2 pays exactly 0.30", () => {
    expect(settle({ total: "0.30", tenders: [{ method: "cash", amount: "0.1" }, { method: "card", amount: "0.2" }] }).ok).toBe(true);
  });
  it("a zero total cannot be settled (an empty sale is not a sale)", () => {
    expect(settle({ total: "0.00", tenders: [] }).ok).toBe(false);
  });
});

describe("buildSellPayload", () => {
  const cart = [{ variantId: "v1", qty: 2 }];
  it("assembles what /sell needs, with the discount and customer", () => {
    const p = buildSellPayload({ cart, total: "42.50", discountTotal: "7.50", customerId: "c1", tenders: [{ method: "cash", amount: "50" }] });
    expect(p).toMatchObject({ items: [{ variant_id: "v1", quantity: 2 }], discountTotal: "7.50", customerId: "c1", tenderedCash: "50.00" });
    expect(p.tenders).toEqual([{ method: "cash", amount: "42.50" }]);
  });
  it("throws instead of building a payload for an unpaid or empty cart", () => {
    expect(() => buildSellPayload({ cart, total: "42.50", tenders: [{ method: "cash", amount: "10" }] })).toThrow();
    expect(() => buildSellPayload({ cart: [], total: "10.00", tenders: [{ method: "cash", amount: "10" }] })).toThrow();
  });
  it("omits the discount and customer when there are none", () => {
    const p = buildSellPayload({ cart, total: "10.00", tenders: [{ method: "cash", amount: "10" }] });
    expect(p.discountTotal).toBeUndefined();
    expect(p.customerId).toBeUndefined();
  });
});
