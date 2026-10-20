import { describe, expect, it } from "vitest";
import { available, buildCatalog, searchCatalog, variantFromApi } from "./catalogAdapter";

const products = [
  {
    id: "p1",
    title: "قميص قطن",
    status: "active",
    images: [{ url: "https://img/x.png" }],
    variants: [
      { id: "v1", sku: "SH-RED-M", title: "M", price: "25.00", is_active: true, option_values: { color: "أحمر", size: "M" } },
      { id: "v2", sku: "SH-BLU-L", title: "L", price: "27.50", is_active: true, option_values: { color: "أزرق", size: "L" } },
      { id: "v3", sku: "SH-OFF", title: "XL", price: "30.00", is_active: false, option_values: {} },
    ],
  },
  { id: "p2", title: "حذاء", status: "archived", variants: [{ id: "v9", sku: "SHOE", title: "42", price: "99.00", is_active: true, option_values: {} }] },
  { id: "p3", title: "حزام", status: "active", variants: [{ id: "v7", sku: "BELT-1", title: "Default", price: "10.00", is_active: true, option_values: {} }] },
];
const balances = [
  { variant_id: "v1", on_hand: 8, reserved: 3 },
  { variant_id: "v1", on_hand: 2, reserved: 0 }, // a second warehouse row for the same variant
  { variant_id: "v2", on_hand: 0, reserved: 0 },
];

describe("available", () => {
  it("is on_hand minus reserved, summed across warehouses, never negative", () => {
    expect(available(balances, "v1")).toBe(7);
    expect(available([{ variant_id: "x", on_hand: 1, reserved: 5 }], "x")).toBe(0);
    expect(available(balances, "nope")).toBe(0);
  });
});

describe("variantFromApi", () => {
  it("keeps price as exact money and reads color/size from option_values", () => {
    const v = variantFromApi(products[0], products[0].variants[0], balances);
    expect(v).toMatchObject({ id: "v1", sku: "SH-RED-M", productName: "قميص قطن", color: "أحمر", size: "M", stock: 7, sellPrice: 25 });
  });
  it("a variant without options falls back to its title, never undefined text", () => {
    const v = variantFromApi(products[2], products[2].variants[0], []);
    expect(v.size).toBe("Default");
    expect(v.color).toBe("");
    expect(v.stock).toBe(0);
  });
});

describe("buildCatalog", () => {
  it("lists only sellable variants: active product AND active variant", () => {
    const ids = buildCatalog(products, balances).map((v) => v.id);
    expect(ids).toEqual(["v1", "v2", "v7"]); // v3 inactive variant, v9 archived product
  });
});

describe("searchCatalog", () => {
  const cat = buildCatalog(products, balances);
  it("matches by name, sku and colour, case-insensitively", () => {
    expect(searchCatalog(cat, "قميص").map((v) => v.id)).toEqual(["v1", "v2"]);
    expect(searchCatalog(cat, "belt").map((v) => v.id)).toEqual(["v7"]);
    expect(searchCatalog(cat, "أزرق").map((v) => v.id)).toEqual(["v2"]);
  });
  it("empty query returns nothing, and limit is respected", () => {
    expect(searchCatalog(cat, "  ")).toEqual([]);
    expect(searchCatalog(cat, "قميص", 1)).toHaveLength(1);
  });
});
