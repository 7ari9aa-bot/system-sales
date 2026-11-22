import { describe, expect, it } from "vitest";
import { initialProductForm, nextProductSeed, PRODUCT_SEED_FIELDS } from "./productSeed";

const saved = {
  name: "بنطلون جينز كلاسيك",
  description: "قياس واسع",
  categoryId: "cat-1",
  brandId: "brand-2",
  season: "SS26",
  material: "دنيم",
  threshold: 3,
  sellPrice: 650,
  colors: ["كحلي"],
  sizes: ["L"],
  variants: [{ id: "row-1", sku: "SKU-0003-0101", stock: 12 }],
  imageFiles: [{}],
};

describe("what a saved product leaves behind for the next one", () => {
  it("keeps the shop-wide answers so they are not picked again", () => {
    const seed = nextProductSeed(saved);
    expect(seed).toEqual({ categoryId: "cat-1", brandId: "brand-2", season: "SS26", material: "دنيم", threshold: 3 });
    expect(Object.keys(seed).sort()).toEqual([...PRODUCT_SEED_FIELDS].sort());
  });

  it("drops everything that belongs to the product itself", () => {
    const seed = nextProductSeed(saved);
    for (const field of ["name", "description", "sellPrice", "colors", "sizes", "variants", "imageFiles"]) {
      expect(seed).not.toHaveProperty(field);
    }
  });

  it("survives a half-filled product without inventing values", () => {
    expect(nextProductSeed({ name: "تيشيرت" })).toEqual({ categoryId: "", brandId: "", season: "", material: "", threshold: "" });
    expect(nextProductSeed()).toEqual({ categoryId: "", brandId: "", season: "", material: "", threshold: "" });
  });
});

describe("the empty form after a save", () => {
  it("starts with the kept season, category, brand, fabric and threshold", () => {
    const form = initialProductForm(undefined, nextProductSeed(saved));
    expect(form).toMatchObject({ categoryId: "cat-1", brandId: "brand-2", season: "SS26", material: "دنيم", threshold: 3 });
  });

  it("starts empty where the product is new: name, description, price", () => {
    const form = initialProductForm(undefined, nextProductSeed(saved));
    expect(form).toMatchObject({ name: "", description: "", sellPrice: "" });
  });

  it("still lets the product being edited win over any seed", () => {
    const form = initialProductForm({ ...saved, name: "منتج قديم", season: "FW25" }, nextProductSeed(saved));
    expect(form.name).toBe("منتج قديم");
    expect(form.season).toBe("FW25");
  });

  it("with no seed at all the form is simply empty", () => {
    expect(initialProductForm(undefined, null)).toEqual({
      name: "", categoryId: "", brandId: "", season: "", material: "", description: "", sellPrice: "", threshold: "",
    });
  });
});
