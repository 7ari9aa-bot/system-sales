import { describe, expect, it } from "vitest";
import {
  filterProductRows,
  priceRangeLabel,
  sortProductRows,
  statusCounts,
  toProductRow,
} from "./productRows";

const raw = (over = {}) => ({
  id: "p1",
  title: "تيشيرت قطن",
  slug: "tee-cotton",
  status: "active",
  season: "SS26",
  material: "قطن",
  category_id: "c1",
  brand_id: "b1",
  images: [{ url: "https://media/x.jpg" }],
  variants: [
    { id: "v1", sku: "TEE-L", price: "250.00", is_active: true },
    { id: "v2", sku: "TEE-M", price: "200.00", is_active: true },
  ],
  ...over,
});

describe("toProductRow reads the catalogue, not the stock", () => {
  it("counts the variants and gives the price range", () => {
    const row = toProductRow(raw());
    expect(row.variantCount).toBe(2);
    expect([row.priceFrom, row.priceTo]).toEqual([200, 250]);
    expect(priceRangeLabel(row)).toBe("200 – 250 ج.م");
  });

  it("keeps a product that has no stock anywhere: it is still a product", () => {
    // مفيش أي حقل رصيد في الاستجابة، فالموديل الجديد بلا مخزون بيظهر زي أي موديل.
    expect(toProductRow(raw()).variantCount).toBe(2);
  });

  it("shows one price when every variant costs the same, and a dash when there is none", () => {
    expect(priceRangeLabel(toProductRow(raw({ variants: [{ sku: "A", price: "150.00" }] })))).toBe(
      "150 ج.م",
    );
    expect(priceRangeLabel(toProductRow(raw({ variants: [] })))).toBe("—");
  });
});

describe("filterProductRows", () => {
  const rows = [
    toProductRow(raw()),
    toProductRow(raw({ id: "p2", title: "بنطلون جينز", slug: "jeans", category_id: "c2", status: "archived", season: "FW25", material: "دنيم", variants: [{ sku: "JNS-32", price: "400.00" }] })),
    toProductRow(raw({ id: "p3", title: "جاكيت", slug: "jacket", status: "draft", brand_id: "b2", variants: [{ sku: "JKT-M", price: "900.00" }] })),
  ];

  it("searches the name, the handle and any SKU inside the product", () => {
    expect(filterProductRows(rows, { term: "جينز" }).map((r) => r.id)).toEqual(["p2"]);
    expect(filterProductRows(rows, { term: "jns-32" }).map((r) => r.id)).toEqual(["p2"]);
    expect(filterProductRows(rows, { term: "tee" }).map((r) => r.id)).toEqual(["p1"]);
  });

  it("filters by status so an archived model does not sit in the selling list", () => {
    expect(filterProductRows(rows, { status: "active" }).map((r) => r.id)).toEqual(["p1"]);
    expect(filterProductRows(rows, { status: "archived" }).map((r) => r.id)).toEqual(["p2"]);
    expect(filterProductRows(rows, {}).map((r) => r.id)).toEqual(["p1", "p2", "p3"]);
  });

  it("filters by category, brand, season and fabric together", () => {
    expect(filterProductRows(rows, { categoryId: "c2" }).map((r) => r.id)).toEqual(["p2"]);
    expect(filterProductRows(rows, { brandId: "b2" }).map((r) => r.id)).toEqual(["p3"]);
    expect(filterProductRows(rows, { season: "FW25", material: "دنيم" }).map((r) => r.id)).toEqual([
      "p2",
    ]);
    expect(filterProductRows(rows, { season: "FW25", material: "قطن" })).toEqual([]);
  });
});

it("sorts by name in Arabic and counts each status", () => {
  const rows = [
    toProductRow(raw({ id: "p2", title: "بنطلون" })),
    toProductRow(raw({ id: "p1", title: "تيشيرت" })),
    toProductRow(raw({ id: "p3", title: "أرشيف", status: "archived" })),
  ];
  expect(sortProductRows(rows).map((r) => r.title)).toEqual(["أرشيف", "بنطلون", "تيشيرت"]);
  expect(statusCounts(rows)).toEqual({ active: 2, draft: 0, archived: 1 });
});
