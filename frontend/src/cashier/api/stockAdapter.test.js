import { describe, expect, it } from "vitest";
import { costLabel, stockQuery, stockRowFromApi, stockSummaryFromApi } from "./stockAdapter";

const raw = (over = {}) => ({
  variant_id: "v1",
  product_id: "p1",
  product_title: "قميص",
  category_id: "c1",
  category: "قمصان",
  sku: "SH-1",
  options: { color: "أسود", size: "L" },
  barcode: "2000000010000",
  price: "199.50",
  avg_cost: "120.25",
  on_hand: 7,
  reserved: 1,
  reorder_level: 5,
  status: "in",
  stock_cost_value: "841.75",
  stock_retail_value: "1396.50",
  ...over,
});

describe("stockRowFromApi", () => {
  it("renames the fields and parses the money text once", () => {
    const r = stockRowFromApi(raw());
    expect(r).toMatchObject({ id: "v1", productName: "قميص", color: "أسود", size: "L", sellPrice: 199.5, buyPrice: 120.25, stock: 7, threshold: 5 });
    expect(r.costValue).toBe(841.75);
  });

  it("keeps an UNKNOWN cost null, never zero", () => {
    const r = stockRowFromApi(raw({ avg_cost: null, stock_cost_value: null }));
    expect(r.buyPrice).toBeNull();
    expect(r.costKnown).toBe(false);
    expect(r.costValue).toBeNull();
  });

  it("keeps a real zero cost as zero (a free sample is not an unknown cost)", () => {
    const r = stockRowFromApi(raw({ avg_cost: "0.00", stock_cost_value: "0.00" }));
    expect(r.buyPrice).toBe(0);
    expect(r.costKnown).toBe(true);
  });

  it("takes the status from the server and falls back to 'in' for something unknown", () => {
    expect(stockRowFromApi(raw({ status: "low" })).status).toBe("low");
    expect(stockRowFromApi(raw({ status: "out", on_hand: 0 })).status).toBe("out");
    expect(stockRowFromApi(raw({ status: "weird" })).status).toBe("in");
  });

  it("does not drop an option other than colour and size", () => {
    const r = stockRowFromApi(raw({ options: { color: "أحمر", size: "M", material: "قطن" } }));
    expect(r.size).toBe("M / قطن");
  });

  it("survives a variant with no options, no barcode and no category", () => {
    const r = stockRowFromApi(raw({ options: null, barcode: null, category: null, category_id: null, sku: null }));
    expect(r).toMatchObject({ color: "", size: "", barcode: "", category: "", categoryId: null, sku: "" });
  });

  it("level 0 means no alert is configured", () => {
    expect(stockRowFromApi(raw({ reorder_level: 0 })).threshold).toBe(0);
  });
});

describe("stockSummaryFromApi", () => {
  it("maps the server totals and counts the unknown costs", () => {
    const s = stockSummaryFromApi({ variants: 40, pieces: 300, out: 3, low: 5, alerts: 8, cost_value: "9000.50", retail_value: "15000.00", unknown_cost_variants: 2 });
    expect(s).toEqual({ variants: 40, pieces: 300, out: 3, low: 5, alerts: 8, costValue: 9000.5, retailValue: 15000, unknownCost: 2 });
  });

  it("is all zeros for an empty or missing answer", () => {
    expect(stockSummaryFromApi(undefined)).toEqual({ variants: 0, pieces: 0, out: 0, low: 0, alerts: 0, costValue: 0, retailValue: 0, unknownCost: 0 });
  });
});

describe("stockQuery", () => {
  it("leaves empty filters out and always carries the limit", () => {
    expect(stockQuery()).toBe("limit=1000");
  });

  it("sends the filters it is given, trimmed", () => {
    const q = new URLSearchParams(stockQuery({ term: "  قميص ", categoryId: "c1", status: "low" }));
    expect(q.get("term")).toBe("قميص");
    expect(q.get("category_id")).toBe("c1");
    expect(q.get("status")).toBe("low");
  });

  it("never sends a status the server would reject", () => {
    expect(new URLSearchParams(stockQuery({ status: "broken" })).has("status")).toBe(false);
  });
});

describe("costLabel", () => {
  const fmt = (n) => `${n} ج`;
  it("says unknown for null and formats a real value, including zero", () => {
    expect(costLabel(null, fmt)).toBe("غير معروفة");
    expect(costLabel(undefined, fmt)).toBe("غير معروفة");
    expect(costLabel(0, fmt)).toBe("0 ج");
    expect(costLabel(120.25, fmt)).toBe("120.25 ج");
  });
});
