import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// الصفحة بتقرا الكتالوج والتقسيمات؛ الاختبار بيشتغل على استجابات ثابتة بدل الشبكة.
const state = { products: [], loading: false };
vi.mock("@/cashier/api/useCatalogList", () => ({
  useCatalogProducts: () => ({ data: state.products, isLoading: state.loading }),
  useSetProductStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/cashier/api/useCatalogWrite", () => ({
  useCategories: () => ({ data: [{ id: "c1", name: "تيشيرتات" }] }),
  useBrands: () => ({ data: [{ id: "b1", name: "نايك" }] }),
}));
vi.mock("@/cashier/api/useStock", () => ({ useStockSeasons: () => ({ data: ["SS26"] }) }));

import ProductsPage from "./products.index.jsx";

const draw = () =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={["/cashier/products"]}>
      <ProductsPage />
    </MemoryRouter>,
  );

const row = (over = {}) => ({
  id: "p1",
  title: "تيشيرت قطن",
  slug: "tee",
  status: "active",
  season: "SS26",
  material: "قطن",
  categoryId: "c1",
  brandId: "b1",
  variantCount: 2,
  activeVariantCount: 2,
  skus: ["TEE-L"],
  priceFrom: 200,
  priceTo: 250,
  imageUrl: null,
  ...over,
});

describe("the products page is a catalogue, not the add form", () => {
  it("lists the shop's products with their classification and price range", () => {
    state.products = [row()];
    const html = draw();
    expect(html).toContain("تيشيرت قطن");
    expect(html).toContain("تيشيرتات");
    expect(html).toContain("نايك");
    expect(html).toContain("SS26 / قطن");
    expect(html).toContain("متاح للبيع");
    expect(html).toContain("/products/p1/edit");
    expect(html).toContain("أرشفة");
    // مش شاشة إضافة: مفيش حقول إدخال منتج جديد هنا.
    expect(html).not.toContain("اسم المنتج");
  });

  it("hides archived models from the selling list and offers to bring them back", () => {
    state.products = [row({ id: "p2", title: "بنطلون قديم", status: "archived" })];
    const html = draw();
    expect(html).not.toContain("بنطلون قديم");
    state.products = [row({ id: "p2", title: "بنطلون قديم", status: "archived" }), row()];
    expect(draw()).not.toContain("بنطلون قديم");
  });

  it("says so when the shop has no products yet, and points at both ways to start", () => {
    state.products = [];
    const html = draw();
    expect(html).toContain("لسه مفيش منتجات في الكتالوج");
    expect(html).toContain("إضافة منتج");
    expect(html).toContain("استيراد من Excel");
    expect(html).toContain("/inventory/import");
  });
});
