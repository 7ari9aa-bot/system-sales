import { describe, expect, it } from "vitest";
import { clampLabelQty, countsFromOrder, labelProducts } from "./labelsAdapter";

const stock = [
  { id: "v1", productId: "p1", productName: "قميص", sku: "S-1", category: "قمصان", color: "أسود", size: "M", barcode: "111", sellPrice: 100, stock: 4 },
  { id: "v2", productId: "p1", productName: "قميص", sku: "S-2", category: "قمصان", color: "أسود", size: "L", barcode: "112", sellPrice: 100, stock: 6 },
  { id: "v3", productId: "p2", productName: "بنطلون", sku: "P-1", category: "بناطيل", color: "أزرق", size: "32", barcode: "", sellPrice: 250, stock: 0 },
];

describe("labelProducts", () => {
  const out = labelProducts(stock);
  it("groups variants under their product", () => {
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ name: "قميص", variantsCount: 2, totalStock: 10, colors: ["أسود"], sizes: ["M", "L"], category: "قمصان" });
  });
  it("keeps each variant's own barcode and price", () => {
    expect(out[0].variants.map((v) => v.barcode)).toEqual(["111", "112"]);
    expect(out[1].variants[0]).toMatchObject({ barcode: "", price: 250 });
  });
  it("is empty for no stock", () => {
    expect(labelProducts([])).toEqual([]);
    expect(labelProducts(undefined)).toEqual([]);
  });
});

describe("clampLabelQty", () => {
  it("keeps it a whole number between 0 and 99", () => {
    expect(clampLabelQty("5")).toBe(5);
    expect(clampLabelQty(2.9)).toBe(2);
    expect(clampLabelQty(-3)).toBe(0);
    expect(clampLabelQty(500)).toBe(99);
    expect(clampLabelQty("abc")).toBe(0);
  });
});

describe("countsFromOrder", () => {
  const variants = new Map(labelProducts(stock).flatMap((p) => p.variants).map((v) => [v.id, v]));
  const received = { receipt: "received", items: [{ variantId: "v1", qty: 3 }, { variantId: "v2", qty: 200 }, { variantId: "v3", qty: 2 }, { variantId: "gone", qty: 1 }] };
  it("counts a received invoice per variant, capped at 99", () => {
    const r = countsFromOrder(received, variants);
    expect(r.counts).toEqual({ v1: 3, v2: 99 });
    expect(r.pieces).toBe(102);
  });
  it("skips (and reports) a variant with no barcode", () => {
    expect(countsFromOrder(received, variants).skipped).toEqual(["v3"]);
  });
  it("adds repeated lines of the same variant", () => {
    const r = countsFromOrder({ receipt: "received", items: [{ variantId: "v1", qty: 2 }, { variantId: "v1", qty: 4 }] }, variants);
    expect(r.counts.v1).toBe(6);
  });
  it("ignores a draft or cancelled invoice", () => {
    expect(countsFromOrder({ ...received, receipt: "draft" }, variants).counts).toEqual({});
    expect(countsFromOrder({ ...received, receipt: "cancelled" }, variants).pieces).toBe(0);
  });
});
