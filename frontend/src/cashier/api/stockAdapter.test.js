import { describe, expect, it } from "vitest";
import { costLabel, materialChoices, seasonChoices, stockQuery, stockRowFromApi, stockSummaryFromApi } from "./stockAdapter";

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

describe("stockRowFromApi season and brand", () => {
  it("carries the season and the brand of the product", () => {
    const row = stockRowFromApi(raw({ season: "SS26", brand_id: "b1" }));
    expect(row.season).toBe("SS26");
    expect(row.brandId).toBe("b1");
  });
  it("a product with neither gives empty text and null, never undefined", () => {
    const row = stockRowFromApi(raw({ season: null, brand_id: null }));
    expect(row.season).toBe("");
    expect(row.brandId).toBeNull();
    const bare = stockRowFromApi(raw());
    expect(bare.season).toBe("");
    expect(bare.brandId).toBeNull();
  });
});

describe("stockQuery season and brand", () => {
  it("sends them when chosen, the season trimmed", () => {
    const q = new URLSearchParams(stockQuery({ brandId: "b1", season: "  SS26 " }));
    expect(q.get("brand_id")).toBe("b1");
    expect(q.get("season")).toBe("SS26");
  });
  it("leaves them out when empty or blank, so 'all' means no filter", () => {
    const q = new URLSearchParams(stockQuery({ brandId: "", season: "   " }));
    expect(q.has("brand_id")).toBe(false);
    expect(q.has("season")).toBe(false);
  });
  it("combines with the other filters", () => {
    const q = new URLSearchParams(stockQuery({ term: "قميص", categoryId: "c1", brandId: "b1", season: "AW26", status: "low" }));
    expect([...q.keys()].sort()).toEqual(["brand_id", "category_id", "limit", "season", "status", "term"]);
  });
});

describe("seasonChoices", () => {
  const rows = (...seasons) => seasons.map((season) => ({ season }));
  it("lists each season the shop used once", () => {
    expect(seasonChoices(rows("SS26", "AW26", "SS26"))).toEqual(["AW26", "SS26"]);
  });
  it("treats SS26 and ss26 as one season and keeps the first spelling", () => {
    expect(seasonChoices(rows("SS26", "ss26", " Ss26 "))).toEqual(["SS26"]);
  });
  it("leaves out products with no season", () => {
    expect(seasonChoices(rows("", null, undefined, "  ", "SS26"))).toEqual(["SS26"]);
  });
  it("is empty for no rows, and for nothing at all", () => {
    expect(seasonChoices([])).toEqual([]);
    expect(seasonChoices(undefined)).toEqual([]);
  });
  it("is sorted, so the list does not jump about when stock changes", () => {
    expect(seasonChoices(rows("صيف 26", "شتاء 26", "خريف 25"))).toEqual(["خريف 25", "شتاء 26", "صيف 26"]);
  });
});

describe("stockRowFromApi material", () => {
  it("carries the material of the product", () => {
    expect(stockRowFromApi(raw({ material: "قطن" })).material).toBe("قطن");
  });
  it("trims it, and a product with no material gives empty text, never undefined or 'null'", () => {
    expect(stockRowFromApi(raw({ material: "  كتان " })).material).toBe("كتان");
    expect(stockRowFromApi(raw({ material: null })).material).toBe("");
    expect(stockRowFromApi(raw()).material).toBe("");
    expect(stockRowFromApi(raw({ material: "null" })).material).toBe("");
  });
});

describe("stockQuery material", () => {
  it("sends the material when chosen, trimmed", () => {
    const q = new URLSearchParams(stockQuery({ material: "  قطن " }));
    expect(q.get("material")).toBe("قطن");
  });
  it("leaves it out when empty or blank, so 'all materials' means no filter", () => {
    expect(new URLSearchParams(stockQuery({ material: "" })).has("material")).toBe(false);
    expect(new URLSearchParams(stockQuery({ material: "   " })).has("material")).toBe(false);
  });
  it("never sends the text 'null' as a material filter", () => {
    expect(new URLSearchParams(stockQuery({ material: "null" })).has("material")).toBe(false);
    expect(new URLSearchParams(stockQuery({ material: null })).has("material")).toBe(false);
  });
  it("combines with the other filters", () => {
    const q = new URLSearchParams(stockQuery({ term: "قميص", categoryId: "c1", brandId: "b1", season: "AW26", material: "قطن", status: "low" }));
    expect([...q.keys()].sort()).toEqual(["brand_id", "category_id", "limit", "material", "season", "status", "term"]);
    expect(q.get("material")).toBe("قطن");
  });
});

describe("materialChoices", () => {
  const rows = (...materials) => materials.map((material) => ({ material }));
  it("lists each material the shop used once", () => {
    expect(materialChoices(rows("قطن", "كتان", "قطن"))).toEqual(["قطن", "كتان"]);
  });
  it("treats 'Cotton' and 'cotton' as one material and keeps the first spelling", () => {
    expect(materialChoices(rows("Cotton", "cotton", " COTTON "))).toEqual(["Cotton"]);
  });
  it("leaves out products with no material, and never lists the text 'null'", () => {
    expect(materialChoices(rows("", null, undefined, "  ", "null", "قطن"))).toEqual(["قطن"]);
  });
  it("is empty for no rows, and for nothing at all", () => {
    expect(materialChoices([])).toEqual([]);
    expect(materialChoices(undefined)).toEqual([]);
  });
  it("is sorted, so the list does not jump about when stock changes", () => {
    expect(materialChoices(rows("صوف", "قطن", "كتان"))).toEqual(["صوف", "قطن", "كتان"]);
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
