import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { editProductPath } from "./ProductDetailsDialog";

const src = readFileSync(new URL("./ProductDetailsDialog.jsx", import.meta.url), "utf8");

describe("the product details dialog leads to the edit screen", () => {
  it("builds the edit address from the product's own id", () => {
    expect(editProductPath({ id: "p-1" })).toBe("/cashier/products/p-1/edit");
  });
  it("encodes an id so it can never break out of the path", () => {
    expect(editProductPath({ id: "a/b?c" })).toBe("/cashier/products/a%2Fb%3Fc/edit");
  });
  it("has no address for a product without an id", () => {
    expect(editProductPath({})).toBeNull();
    expect(editProductPath(null)).toBeNull();
  });
  it("shows an orange, visible 'تعديل المنتج' link that goes to that address", () => {
    expect(src).toContain("تعديل المنتج");
    expect(src).toMatch(/<Link to=\{editTo\}/);
    expect(src).toContain("!bg-[#E8761A]");
    expect(src).toContain("!text-white");
  });
  it("shows the link only when there is an address", () => {
    expect(src).toMatch(/\{editTo && \(/);
  });
});
