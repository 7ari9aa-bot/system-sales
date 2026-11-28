import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// الصفحة كانت بتبعت لـ/products/:id/edit اللي بقى 404 بعد ما المنتجات انتقلت
// تحت /cashier. الاختبار بيثبت إن كل زابط في السجل بيروح على مسار موجود فعلًا.
vi.mock("@/applications/apparel/api/useCatalogList", () => ({
  PAGE_SIZE: 50,
  useCatalogPage: () => ({
    data: {
      total: 1,
      rows: [
        {
          id: "p-1",
          title: "تجربة تيشيرت قطن",
          slug: "tee",
          status: "active",
          priceMin: "300.00",
          priceMax: "300.00",
          variantCount: 2,
          skus: ["SKU-0001-0101"],
          season: "صيف 26",
          material: "قطن",
          categoryId: null,
          brandId: null,
          imageUrl: null,
        },
      ],
    },
    isLoading: false,
  }),
  useSetProductStatus: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/applications/apparel/api/useCatalogWrite", () => ({
  useCategories: () => ({ data: [] }),
  useBrands: () => ({ data: [] }),
}));
vi.mock("@/applications/apparel/api/useStock", () => ({ useStockSeasons: () => ({ data: [] }) }));

import ProductsCatalogPage from "./ProductsCatalogPage";

const html = () =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ProductsCatalogPage />
    </MemoryRouter>,
  );

const hrefs = (markup) => [...markup.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);

describe("products catalog links", () => {
  it("opens the editor on the cashier route, not the dead /products one", () => {
    const links = hrefs(html());
    expect(links).toContain("/cashier/products/p-1/edit");
    expect(links.filter((h) => h === "/products/p-1/edit")).toEqual([]);
  });

  it("adds a product on the cashier route", () => {
    const links = hrefs(html());
    expect(links).toContain("/cashier/products/new");
    expect(links.filter((h) => h === "/products/new")).toEqual([]);
  });
});
