import { describe, expect, it } from "vitest";
import { cartItems, clampQty, restoreRemovedLine } from "./checkout";

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

  it("a line's own discount travels WITH the line, so the server can store it per line", () => {
    expect(
      cartItems([
        { variantId: "a", qty: 1, discountPct: 50 },
        { variantId: "b", qty: 1, discountPct: 0 },
        { variantId: "c", qty: 2, discountPct: 12.5 },
      ]),
    ).toEqual([
      { variant_id: "a", quantity: 1, discount_pct: "50.00" },
      { variant_id: "b", quantity: 1 },
      { variant_id: "c", quantity: 2, discount_pct: "12.50" },
    ]);
  });
});

describe("restoreRemovedLine (undo a deleted line)", () => {
  const A = { lineId: "a", variantId: "va", name: "A", price: 100, qty: 3, stock: 10, discountPct: 10, discount: 30 };
  const B = { lineId: "b", variantId: "vb", name: "B", price: 50, qty: 1, stock: 5, discountPct: 0, discount: 0 };
  const C = { lineId: "c", variantId: "vc", name: "C", price: 20, qty: 2, stock: 5, discountPct: 0, discount: 0 };

  it("puts the same line back where it was, with its quantity and discount", () => {
    const r = restoreRemovedLine([B, C], A, 0, 10);
    expect(r.ok).toBe(true);
    expect(r.lines.map((l) => l.variantId)).toEqual(["va", "vb", "vc"]);
    expect(r.lines[0]).toMatchObject({ qty: 3, discountPct: 10, discount: 30 });
    expect(r.clamped).toBe(false);
  });

  it("restores into the middle and at the end", () => {
    expect(restoreRemovedLine([A, C], B, 1, 5).lines.map((l) => l.variantId)).toEqual(["va", "vb", "vc"]);
    expect(restoreRemovedLine([A, B], C, 99, 5).lines.map((l) => l.variantId)).toEqual(["va", "vb", "vc"]);
  });

  it("never restores more than is on the shelf now, and recomputes the discount for the new quantity", () => {
    const r = restoreRemovedLine([B], A, 0, 2);
    expect(r.lines[0].qty).toBe(2);
    expect(r.lines[0].discount).toBe(20); // 100 x 2 x 10%
    expect(r.clamped).toBe(true);
  });

  it("refuses when the item is sold out now", () => {
    expect(restoreRemovedLine([B], A, 0, 0)).toMatchObject({ ok: false });
  });

  it("does not duplicate a line the cashier added again meanwhile", () => {
    const again = { ...A, qty: 1, discountPct: 0, discount: 0 };
    const r = restoreRemovedLine([again, B], A, 0, 10);
    expect(r.lines).toHaveLength(2);
    expect(r.lines[0].qty).toBe(1);
  });

  it("does not mutate the cart it was given", () => {
    const cart = [B, C];
    restoreRemovedLine(cart, A, 0, 10);
    expect(cart).toHaveLength(2);
  });
});
