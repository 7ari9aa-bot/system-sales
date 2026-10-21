import { describe, expect, it } from "vitest";
import { groupVariantsByProduct, resolveOpenProduct, worstStatus } from "./inventoryGroups";

const v = (over = {}) => ({ id: "v", productId: "p1", productName: "قميص", sku: "S", category: "قمصان", sellPrice: 100, stock: 5, status: "in", ...over });

describe("worstStatus", () => {
  it("is the most severe status present", () => {
    expect(worstStatus(["in", "in"])).toBe("in");
    expect(worstStatus(["in", "low", "in"])).toBe("low");
    expect(worstStatus(["low", "out", "in"])).toBe("out");
  });
  it("is 'in' for nothing at all, and ignores an unknown value", () => {
    expect(worstStatus([])).toBe("in");
    expect(worstStatus(["weird", "low"])).toBe("low");
  });
});

describe("groupVariantsByProduct", () => {
  it("sums the stock and counts the variants of one product", () => {
    const [g] = groupVariantsByProduct([v({ stock: 4 }), v({ id: "v2", stock: 6 })]);
    expect(g).toMatchObject({ id: "p1", stock: 10, variantsCount: 2 });
  });

  it("flags the product when ONE size ran out, even though the total looks healthy", () => {
    const [g] = groupVariantsByProduct([v({ id: "a", stock: 50, status: "in" }), v({ id: "b", stock: 0, status: "out" })]);
    expect(g.stock).toBe(50);
    expect(g.statusValue).toBe("out");
  });

  it("keeps different products apart", () => {
    const groups = groupVariantsByProduct([v(), v({ id: "v3", productId: "p2", productName: "بنطلون" })]);
    expect(groups.map((g) => g.id)).toEqual(["p1", "p2"]);
  });
});

describe("resolveOpenProduct", () => {
  const rows = [v({ id: "a", stock: 3, status: "low" })];

  it("is null when nothing is open", () => {
    expect(resolveOpenProduct(null, rows)).toBeNull();
  });

  it("re-derives a grid product from the LIVE rows, so a saved change shows up", () => {
    expect(resolveOpenProduct("p1", rows).statusValue).toBe("low");
    const after = [v({ id: "a", stock: 3, status: "in" })];
    expect(resolveOpenProduct("p1", after).statusValue).toBe("in");
  });

  it("is null when the product is no longer in the rows (filtered out or removed)", () => {
    expect(resolveOpenProduct("p9", rows)).toBeNull();
  });

  it("returns a whole product object untouched", () => {
    const whole = { id: "x", variants: [] };
    expect(resolveOpenProduct(whole, rows)).toBe(whole);
  });
});
