import { describe, expect, it } from "vitest";
import { editLoadProblem, planProductEdit, productToForm, shouldRetryEditLoad } from "./productEdit";

const backend = {
  id: "p1", title: "فستان", description: "وصف", category_id: "c1", brand_id: null,
  variants: [
    { id: "v1", sku: "SKU-1", price: "450.00", option_values: { color: "أسود", size: "M" }, is_active: true },
    { id: "v2", sku: "SKU-2", price: "450.00", option_values: { color: "أسود", size: "L" }, is_active: true },
  ],
};
const before = productToForm(backend, { v1: "2990000000011" });

describe("productToForm images", () => {
  it("carries the product's stored photos to the form", () => {
    const f = productToForm({ ...backend, images: [{ id: "i1", url: "https://x/1.png", position: 0 }] });
    expect(f.images).toEqual([{ id: "i1", url: "https://x/1.png", position: 0 }]);
  });
  it("is an empty list when the product has none", () => {
    expect(productToForm({ ...backend, images: undefined }).images).toEqual([]);
  });
});

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
  it("reads the season of a product, and an unseasonal one as empty text", () => {
    expect(productToForm({ ...backend, season: "SS26" }).season).toBe("SS26");
    expect(productToForm({ ...backend, season: null }).season).toBe("");
    expect(productToForm(backend).season).toBe("");
  });
  it("changing the season sends only the season", () => {
    const b = productToForm({ ...backend, season: "SS26" });
    expect(planProductEdit(b, { ...structuredClone(b), season: "AW26" }).product).toEqual({ season: "AW26" });
  });
  it("clearing the season sends null, not an empty string", () => {
    const b = productToForm({ ...backend, season: "SS26" });
    expect(planProductEdit(b, { ...structuredClone(b), season: "  " }).product).toEqual({ season: null });
  });
  it("an untouched season sends nothing, so a product edited for another reason keeps it", () => {
    const b = productToForm({ ...backend, season: "SS26" });
    const plan = planProductEdit(b, { ...structuredClone(b), name: "اسم جديد" });
    expect(plan.product).toEqual({ title: "اسم جديد" });
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
  it("correcting a barcode the variant already has REPLACES it: the old id rides on the new code", () => {
    const withIds = productToForm(backend, { v1: "2991000102947" }, { v1: "ident-1" });
    const after = structuredClone(withIds);
    after.variants[0].barcode = "2991000102949";
    const plan = planProductEdit(withIds, after);
    expect(plan.newBarcodes).toEqual([{ variantId: "v1", value: "2991000102949", replacesId: "ident-1" }]);
  });
  it("a first barcode on a variant that had none replaces nothing", () => {
    const withIds = productToForm(backend, { v1: "2991000102947" }, { v1: "ident-1" });
    const after = structuredClone(withIds);
    after.variants[1].barcode = "2990000000028";
    expect(planProductEdit(withIds, after).newBarcodes).toEqual([
      { variantId: "v2", value: "2990000000028" },
    ]);
  });
  it("the form carries the id of the barcode it shows", () => {
    const f = productToForm(backend, { v1: "2991000102947" }, { v1: "ident-1" });
    expect(f.variants[0]).toMatchObject({ barcode: "2991000102947", barcodeId: "ident-1" });
    expect(f.variants[1].barcodeId).toBe("");
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

describe("material: read into the form and sent only when it changed", () => {
  it("reads the product's material into the form", () => {
    expect(productToForm({ ...backend, material: "قطن" }).material).toBe("قطن");
    expect(productToForm({ ...backend, material: "  كتان  " }).material).toBe("كتان");
  });
  it("a product with no material reads as empty text, never 'null' or undefined", () => {
    expect(productToForm({ ...backend, material: null }).material).toBe("");
    expect(productToForm(backend).material).toBe("");
    expect(productToForm({ ...backend, material: "null" }).material).toBe("");
  });
  it("changing the material sends only the material, trimmed", () => {
    const b = productToForm({ ...backend, material: "قطن" });
    expect(planProductEdit(b, { ...structuredClone(b), material: "  كتان " }).product).toEqual({ material: "كتان" });
  });
  it("clearing the material sends null, not an empty string", () => {
    const b = productToForm({ ...backend, material: "قطن" });
    expect(planProductEdit(b, { ...structuredClone(b), material: "   " }).product).toEqual({ material: null });
    expect(planProductEdit(b, { ...structuredClone(b), material: null }).product).toEqual({ material: null });
  });
  it("the text 'null' is never sent as a material: it clears it like a blank does", () => {
    const b = productToForm({ ...backend, material: "قطن" });
    expect(planProductEdit(b, { ...structuredClone(b), material: "null" }).product).toEqual({ material: null });
    expect(planProductEdit(b, { ...structuredClone(b), material: " NULL " }).product).toEqual({ material: null });
  });
  it("an untouched material sends nothing, so a product edited for another reason keeps it", () => {
    const b = productToForm({ ...backend, material: "قطن" });
    const plan = planProductEdit(b, { ...structuredClone(b), name: "اسم جديد" });
    expect(plan.product).toEqual({ title: "اسم جديد" });
    expect(plan.product).not.toHaveProperty("material");
  });
  it("adding a material to a product that had none sends it", () => {
    expect(planProductEdit(before, { ...structuredClone(before), material: "صوف" }).product).toEqual({ material: "صوف" });
  });
  it("a whitespace-only change is not a change", () => {
    const b = productToForm({ ...backend, material: "قطن" });
    expect(planProductEdit(b, { ...structuredClone(b), material: "  قطن  " }).empty).toBe(true);
  });
  it("material and season are independent: changing both sends both", () => {
    const b = productToForm({ ...backend, season: "SS26", material: "قطن" });
    expect(planProductEdit(b, { ...structuredClone(b), season: "AW26", material: "كتان" }).product).toEqual({
      season: "AW26",
      material: "كتان",
    });
  });
});

describe("what a failed product load means for the owner", () => {
  it("says the product is missing only when the server says it does not exist", () => {
    expect(editLoadProblem({ status: 404 })).toBe("missing");
  });
  it("calls a server or network failure a temporary problem, never a missing product", () => {
    expect(editLoadProblem({ status: 503 })).toBe("temporary");
    expect(editLoadProblem({ status: 500 })).toBe("temporary");
    expect(editLoadProblem({ status: 0 })).toBe("temporary");
    expect(editLoadProblem(new Error("boom"))).toBe("temporary");
    expect(editLoadProblem(undefined)).toBe("temporary");
  });
  it("calls a refused request a problem with the link, not a missing product", () => {
    expect(editLoadProblem({ status: 403 })).toBe("forbidden");
    expect(editLoadProblem({ status: 401 })).toBe("forbidden");
  });
  it("retries a temporary failure a few times and then stops", () => {
    expect(shouldRetryEditLoad(0, { status: 503 })).toBe(true);
    expect(shouldRetryEditLoad(2, { status: 503 })).toBe(true);
    expect(shouldRetryEditLoad(3, { status: 503 })).toBe(false);
  });
  it("never retries a missing product or a refusal", () => {
    expect(shouldRetryEditLoad(0, { status: 404 })).toBe(false);
    expect(shouldRetryEditLoad(0, { status: 403 })).toBe(false);
  });
});
