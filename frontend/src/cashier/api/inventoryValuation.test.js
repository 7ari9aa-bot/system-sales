import { describe, expect, it } from "vitest";
import { summarizeValuation, valuationByCategory } from "./inventoryValuation";

const row = (o) => ({ productId: "p1", category: "تيشيرتات", stock: 1, retailValue: 100, costValue: 60, ...o });

describe("valuationByCategory", () => {
  it("groups by category and sums pieces, cost and retail exactly", () => {
    const g = valuationByCategory([row({ stock: 2, retailValue: 200, costValue: 120 }), row({ productId: "p2", stock: 3, retailValue: 0.3, costValue: 0.1 }), row({ category: "بناطيل", retailValue: 50, costValue: 20 })]);
    const t = g.find((x) => x.category === "تيشيرتات");
    expect(t).toMatchObject({ items: 2, variants: 2, pieces: 5, cost: 120.1, retail: 200.3 });
    expect(g.map((x) => x.category)).toEqual(["تيشيرتات", "بناطيل"]); // biggest retail value first
  });
  it("an UNKNOWN cost is not zero: it is counted as missing and kept out of cost and margin", () => {
    const [g] = valuationByCategory([row({ retailValue: 100, costValue: 60 }), row({ productId: "p2", retailValue: 100, costValue: null })]);
    expect(g).toMatchObject({ cost: 60, retail: 200, unknownCost: 1, retailOfKnown: 100 });
    expect(g.margin).toBe(40); // (100-60)/100, NOT (200-60)/200 = 70
  });
  it("no known cost at all means no margin, not 100%", () => {
    const [g] = valuationByCategory([row({ costValue: null })]);
    expect(g.margin).toBeNull();
    expect(g.cost).toBe(0);
  });
  it("a variant without a category lands in its own group", () => {
    expect(valuationByCategory([row({ category: "" })])[0].category).toBe("بدون تصنيف");
  });
  it("no rows is an empty report", () => expect(valuationByCategory()).toEqual([]));
});

describe("summarizeValuation", () => {
  it("totals and a margin that ignores unknown-cost stock", () => {
    const s = summarizeValuation(valuationByCategory([row({ retailValue: 100, costValue: 60 }), row({ category: "بناطيل", retailValue: 300, costValue: null })]));
    expect(s).toMatchObject({ cost: 60, retail: 400, unknownCost: 1, margin: 40, truncated: false });
  });
  it("flags a result that may be cut at the load cap", () => {
    const rows = Array.from({ length: 1000 }, (_, i) => row({ productId: `p${i}` }));
    expect(summarizeValuation(valuationByCategory(rows)).truncated).toBe(true);
  });
});
