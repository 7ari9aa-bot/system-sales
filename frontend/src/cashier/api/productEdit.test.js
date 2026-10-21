import { describe, expect, it } from "vitest";
import { planProductEdit, productToForm } from "./productEdit";

const backend = {
  id: "p1", title: "فستان", description: "وصف", category_id: "c1", brand_id: null,
  variants: [
    { id: "v1", sku: "SKU-1", price: "450.00", option_values: { color: "أسود", size: "M" }, is_active: true },
    { id: "v2", sku: "SKU-2", price: "450.00", option_values: { color: "أسود", size: "L" }, is_active: true },
  ],
};
const before = productToForm(backend, { v1: "2990000000011" });

describe("productToForm", () => {
  it("reads colours, sizes, barcodes and ids from the backend shape", () => {
    expect(before.name).toBe("فستان");
    expect(before.colors).toEqual(["أسود"]);
    expect(before.sizes).toEqual(["M", "L"]);
    expect(before.variants[0]).toMatchObject({ id: "v1", barcode: "2990000000011", sellPrice: "450.00" });
    expect(before.brandId).toBe("");
  });
});

describe("planProductEdit sends only what changed", () => {
  it("nothing changed -> empty plan", () => {
    expect(planProductEdit(before, structuredClone(before)).empty).toBe(true);
  });
  it("name + category change -> one product patch, no variant calls", () => {
    const after = { ...structuredClone(before), name: "فستان صيفي", categoryId: "c2" };
    const plan = planProductEdit(before, after);
    expect(plan.product).toEqual({ title: "فستان صيفي", category_id: "c2" });
    expect(plan.variantPatches).toEqual([]);
  });
  it("clearing the brand sends null, not an empty string", () => {
    const b = { ...structuredClone(before), brandId: "b1" };
    expect(planProductEdit(b, { ...structuredClone(b), brandId: "" }).product).toEqual({ brand_id: null });
  });
  it("a price change patches only that variant", () => {
    const after = structuredClone(before);
    after.variants[1].sellPrice = "500";
    const plan = planProductEdit(before, after);
    expect(plan.variantPatches).toEqual([{ id: "v2", patch: { price: "500.00" } }]);
  });
  it("a typed barcode on an existing variant is added; an unchanged one is not re-sent", () => {
    const after = structuredClone(before);
    after.variants[1].barcode = "2990000000028";
    const plan = planProductEdit(before, after);
    expect(plan.newBarcodes).toEqual([{ variantId: "v2", value: "2990000000028" }]);
  });
  it("a row without an id is a new combination", () => {
    const after = structuredClone(before);
    after.variants.push({ id: undefined, sku: "SKU-3", color: "أحمر", size: "M", sellPrice: "450", barcode: "", stock: 0 });
    expect(planProductEdit(before, after).newVariants).toHaveLength(1);
  });
  it("a bad price throws before any request is planned", () => {
    const after = structuredClone(before);
    after.variants[0].sellPrice = "abc";
    expect(() => planProductEdit(before, after)).toThrow();
  });
});
