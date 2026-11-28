import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// الصفحة بتقرا الكتالوج والتقسيمات؛ الاختبار بيشتغل على استجابات ثابتة بدل الشبكة.
const state = { products: [], loading: false, total: 0, hasMore: false, lastFilters: null };
vi.mock("@/applications/apparel/api/useCatalogList", () => ({
  PAGE_SIZE: 50,
  useCatalogPage: (filters, page) => {
    state.lastFilters = { filters, page };
    return {
      data: { rows: state.products, total: state.total, hasMore: state.hasMore },
      isLoading: state.loading,
    };
  },
  useSetProductStatus: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/applications/apparel/api/useCatalogWrite", () => ({
  useCategories: () => ({ data: [{ id: "c1", name: "تيشيرتات" }] }),
  useBrands: () => ({ data: [{ id: "b1", name: "نايك" }] }),
}));
vi.mock("@/applications/apparel/api/useStock", () => ({ useStockSeasons: () => ({ data: ["SS26"] }) }));

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

  it("asks the server for the selling list only, not for archived models", () => {
    // الفلترة بقت على السيرفر: الشاشة مابتحمّلش الكتالوج كله وتعرض منه.
    state.products = [row()];
    state.total = 1;
    draw();
    expect(state.lastFilters.filters.status).toBe("active");
    expect(state.lastFilters.filters.term).toBe("");
  });

  it("shows how much of the catalogue you are seeing and offers the next page", () => {
    state.products = Array.from({ length: 50 }, (_, i) => row({ id: `p${i}`, title: `منتج ${i}` }));
    state.total = 320;
    state.hasMore = true;
    const html = draw();
    expect(html).toContain("320");
    expect(html).toContain("1–50 من 320");
    expect(html).toContain("التالي");
    expect(html).toContain("صفحة 1 من 7");
  });

  it("says so when the shop has no products yet, and points at both ways to start", () => {
    state.products = [];
    state.total = 0;
    state.hasMore = false;
    const html = draw();
    expect(html).toContain("لا توجد منتجات في الكتالوج بعد");
    expect(html).toContain("إضافة منتج");
    expect(html).toContain("استيراد من Excel");
    expect(html).toContain("/inventory/import");
  });
});
