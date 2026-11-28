import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement } from "react";
import { describe, expect, it, vi } from "vitest";

// The section reads the shop's categories, brands and size sets through hooks; the season field does
// not, so they are given empty answers and the test looks only at what the owner types into.
vi.mock("@/applications/apparel/api/useCatalogWrite", () => {
  const list = () => ({ data: [], isLoading: false });
  const mut = () => ({ mutateAsync: async () => ({}) });
  return { useBrands: list, useCategories: list, useCreateBrand: mut, useCreateCategory: mut };
});
vi.mock("@/applications/apparel/api/useShopOptions", () => ({ useShopOptions: () => ({ options: { sizeSets: [] } }) }));

import ProductBasicsSection from "./ProductBasicsSection";

const draw = (form) =>
  renderToStaticMarkup(<ProductBasicsSection form={form} onPatch={() => {}} sizePreset="clothing" onSizePresetChange={() => {}} />);

const base = { name: "فستان", categoryId: "", brandId: "", description: "" };

describe("the model details section", () => {
  it("has a season box labelled in Arabic", () => {
    expect(draw({ ...base, season: "" })).toContain("الموسم");
  });
  it("shows the season the product already has", () => {
    expect(draw({ ...base, season: "صيف 26" })).toContain('value="صيف 26"');
  });
  it("a product with no season shows an empty box, not the word undefined", () => {
    const html = draw(base);
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("null");
  });
  it("the season is a free text of at most 40 characters, as the server accepts", () => {
    expect(draw({ ...base, season: "" })).toContain('maxLength="40"');
  });
  it("keeps the brand and category pickers", () => {
    const html = draw({ ...base, season: "" });
    expect(html).toContain("العلامة التجارية");
    expect(html).toContain("الفئة");
  });
});

// Walk the element tree the section returns (it is a plain function component) to the season box.
function findSeasonInput(node) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) return node.map(findSeasonInput).find(Boolean) ?? null;
  if (!isValidElement(node)) return null;
  const { props } = node;
  if (props?.placeholder === "مثال: صيف 26") return node;
  return findSeasonInput(props?.children);
}

describe("the season box", () => {
  const patches = [];
  const tree = ProductBasicsSection({ form: { ...base, season: "SS26" }, onPatch: (p) => patches.push(p), sizePreset: "clothing", onSizePresetChange: () => {} });
  const input = findSeasonInput(tree);

  it("is found in the section", () => {
    expect(input).not.toBeNull();
  });
  it("typing in it patches the season and nothing else", () => {
    input.props.onChange({ target: { value: "Aw26 صيف" } });
    expect(patches.at(-1)).toEqual({ season: "Aw26 صيف" });
  });
  it("is always a controlled box: a product that has no season yet gives an empty string, not undefined", () => {
    const noSeason = findSeasonInput(ProductBasicsSection({ form: base, onPatch: () => {}, sizePreset: "clothing", onSizePresetChange: () => {} }));
    expect(noSeason.props.value).toBe("");
  });
});

