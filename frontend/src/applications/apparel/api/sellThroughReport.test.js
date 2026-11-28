import { describe, expect, it } from "vitest";
import { sellThroughQuery, sellThroughRows, sellThroughTotals, shareValue } from "./sellThroughReport";
import { profitQuery } from "./profitReport";
import { shapeSellThrough } from "./useSellThrough";

const NOW = new Date("2026-11-21T10:00:00Z");

describe("shareValue", () => {
  it("reads the server's one-decimal text as a number", () => {
    expect(shareValue("62.5")).toBe(62.5);
    expect(shareValue("100.0")).toBe(100);
    expect(shareValue("0.0")).toBe(0);
  });
  it("keeps 'nothing to be a share of' as null, and a real 0 as 0", () => {
    expect(shareValue(null)).toBeNull();
    expect(shareValue(undefined)).toBeNull();
    expect(shareValue("")).toBeNull();
    expect(shareValue("0.0")).toBe(0);
  });
  it("never lets NaN through", () => {
    expect(shareValue("abc")).toBeNull();
  });
});

describe("sellThroughRows", () => {
  const api = {
    variant_id: "v1",
    model: "قميص",
    season: "SS26",
    material: "قطن",
    brand_id: "b1",
    size: "M",
    colour: "أسود",
    units_sold: 7,
    units_on_hand: 3,
    sold_share: "70.0",
  };
  it("maps every field the server sends", () => {
    expect(sellThroughRows([api])).toEqual([
      {
        id: "v1",
        model: "قميص",
        season: "SS26",
        material: "قطن",
        brandId: "b1",
        size: "M",
        colour: "أسود",
        unitsSold: 7,
        unitsOnHand: 3,
        share: 70,
      },
    ]);
  });
  it("fills missing fields with safe blanks, and a missing share stays null", () => {
    const [r] = sellThroughRows([{ variant_id: "v2" }]);
    expect(r).toMatchObject({ model: "", season: "", material: "", size: "", colour: "", unitsSold: 0, unitsOnHand: 0, share: null });
    expect(r.brandId).toBeNull();
  });
  it("treats the text 'null' as no material", () => {
    expect(sellThroughRows([{ variant_id: "v", material: "null" }])[0].material).toBe("");
  });
  it("copes with no rows at all", () => {
    expect(sellThroughRows()).toEqual([]);
    expect(sellThroughRows(null)).toEqual([]);
  });
});

describe("sellThroughTotals", () => {
  it("maps the totals", () => {
    expect(sellThroughTotals({ units_sold: 10, units_on_hand: 30, sold_share: "25.0" })).toEqual({
      unitsSold: 10,
      unitsOnHand: 30,
      share: 25,
    });
  });
  it("a missing totals object is zeros and a null share", () => {
    expect(sellThroughTotals(undefined)).toEqual({ unitsSold: 0, unitsOnHand: 0, share: null });
  });
});

describe("the query is the profit report's, so the two reports ask about the same window", () => {
  it("is the same function", () => {
    expect(sellThroughQuery).toBe(profitQuery);
  });
  it("sends the filters and leaves the empty ones out", () => {
    const q = new URLSearchParams(sellThroughQuery({ period: "7d", brandId: "b1", season: "SS26", material: "قطن", now: NOW }));
    expect(q.get("brand_id")).toBe("b1");
    expect(q.get("season")).toBe("SS26");
    expect(q.get("material")).toBe("قطن");
    const bare = new URLSearchParams(sellThroughQuery({ period: "7d", now: NOW }));
    expect(bare.has("brand_id") || bare.has("season") || bare.has("material")).toBe(false);
  });
});

describe("shapeSellThrough", () => {
  it("shapes rows and totals together", () => {
    const out = shapeSellThrough({
      rows: [{ variant_id: "v", units_sold: 1, units_on_hand: 1, sold_share: "50.0" }],
      totals: { units_sold: 1, units_on_hand: 1, sold_share: "50.0" },
    });
    expect(out.rows).toHaveLength(1);
    expect(out.totals.share).toBe(50);
  });
  it("an empty answer is an empty table", () => {
    expect(shapeSellThrough(undefined)).toEqual({ rows: [], totals: { unitsSold: 0, unitsOnHand: 0, share: null } });
  });
});
