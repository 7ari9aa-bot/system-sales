import { describe, expect, it } from "vitest";
import { colourLabel, defaultColour, modelsFromCatalog, sizeRank, sizesFor } from "./variantPicker";

const v = (id, productId, productName, colour, size, stock, price = 250) => ({
  id,
  productId,
  productName,
  color: colour,
  size,
  sku: `${productId}-${colour}-${size}`,
  barcode: `B${id}`,
  stock,
  sellPrice: price,
});

const catalog = [
  v("1", "p1", "قميص كتان", "أبيض", "M", 3, 300),
  v("2", "p1", "قميص كتان", "أبيض", "L", 0, 300),
  v("3", "p1", "قميص كتان", "أبيض", "S", 2, 300),
  v("4", "p1", "قميص كتان", "أزرق", "M", 1, 320),
  v("5", "p2", "بنطلون جينز", "أزرق", "38", 4, 500),
  v("6", "p2", "بنطلون جينز", "أزرق", "40", 0, 500),
  v("7", "p2", "بنطلون جينز", "أزرق", "42", 2, 520),
];

describe("modelsFromCatalog", () => {
  it("groups one model's variants into one entry", () => {
    const models = modelsFromCatalog(catalog);
    expect(models.map((m) => m.name)).toEqual(["بنطلون جينز", "قميص كتان"]);
    const shirt = models.find((m) => m.id === "p1");
    expect(shirt.sizeCount).toBe(4);
    expect(shirt.inStock).toBe(3); // the sold-out L is not counted as available
    expect(shirt.priceFrom).toBe(300);
  });

  it("lists the colours of a model once each, in the order the catalog holds them", () => {
    const shirt = modelsFromCatalog(catalog).find((m) => m.id === "p1");
    expect(shirt.colours).toEqual(["أبيض", "أزرق"]);
  });

  it("narrows by a typed term, folded the way the rest of the till folds", () => {
    expect(modelsFromCatalog(catalog, "قميص").map((m) => m.id)).toEqual(["p1"]);
    expect(modelsFromCatalog(catalog, "جينز").map((m) => m.id)).toEqual(["p2"]);
    expect(modelsFromCatalog(catalog, "p2").map((m) => m.id)).toEqual(["p2"]); // by SKU
    expect(modelsFromCatalog(catalog, "  ").map((m) => m.id)).toEqual(["p2", "p1"]);
    expect(modelsFromCatalog(catalog, "حاجة مش موجودة")).toEqual([]);
  });

  it("never drops a model because one of its variants is sold out", () => {
    const models = modelsFromCatalog([v("9", "p9", "جاكيت", "أسود", "M", 0)]);
    expect(models).toHaveLength(1);
    expect(models[0].inStock).toBe(0);
  });
});

describe("defaultColour", () => {
  it("opens on a colour that has something on the shelf", () => {
    const model = { colours: ["أحمر", "أبيض"], variants: [v("1", "p", "x", "أحمر", "M", 0), v("2", "p", "x", "أبيض", "M", 2)] };
    expect(defaultColour(model)).toBe("أبيض");
  });

  it("falls back to the first colour when the whole model is out", () => {
    const model = { colours: ["أحمر", "أبيض"], variants: [v("1", "p", "x", "أحمر", "M", 0), v("2", "p", "x", "أبيض", "M", 0)] };
    expect(defaultColour(model)).toBe("أحمر");
  });

  it("has nothing to say about a model with no variants", () => {
    expect(defaultColour({ colours: [], variants: [] })).toBe("");
    expect(defaultColour(null)).toBe("");
  });
});

describe("sizesFor", () => {
  it("returns one colour's size run in shop order, not alphabetical", () => {
    const shirt = modelsFromCatalog(catalog).find((m) => m.id === "p1");
    expect(sizesFor(shirt, "أبيض").map((s) => s.label)).toEqual(["S", "M", "L"]);
  });

  it("marks a sold-out size so the till can refuse it instead of failing at payment", () => {
    const shirt = modelsFromCatalog(catalog).find((m) => m.id === "p1");
    const sizes = sizesFor(shirt, "أبيض");
    expect(sizes.find((s) => s.label === "L")).toMatchObject({ stock: 0, soldOut: true });
    expect(sizes.find((s) => s.label === "M")).toMatchObject({ stock: 3, soldOut: false, price: 300 });
  });

  it("orders numeric sizes by value", () => {
    const jeans = modelsFromCatalog(catalog).find((m) => m.id === "p2");
    expect(sizesFor(jeans, "أزرق").map((s) => s.label)).toEqual(["38", "40", "42"]);
  });

  it("is empty for a colour the model does not come in", () => {
    const shirt = modelsFromCatalog(catalog).find((m) => m.id === "p1");
    expect(sizesFor(shirt, "أخضر")).toEqual([]);
    expect(sizesFor(null, "أبيض")).toEqual([]);
  });
});

describe("labels and ranking", () => {
  it("names a colour or size that was never entered instead of leaving a gap", () => {
    expect(colourLabel("")).toBe("بلا لون");
    expect(colourLabel("  ")).toBe("بلا لون");
    expect(colourLabel("أحمر")).toBe("أحمر");
  });

  it("ranks letter sizes before numbers before anything else", () => {
    expect(sizeRank("XS")[0]).toBe(0);
    expect(sizeRank("xl")[0]).toBe(0);
    expect(sizeRank("40")[0]).toBe(1);
    expect(sizeRank("واسع")[0]).toBe(2);
    expect(sizeRank("S")[1]).toBeLessThan(sizeRank("M")[1]);
  });
});
