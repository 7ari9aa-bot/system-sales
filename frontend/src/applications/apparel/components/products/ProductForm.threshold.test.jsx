import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

// الحقل العام «حد التنبيه» كان بيكتب في حالة النموذج بس، والتركيبات بتفضل على قيمتها،
// فالحفظ يقول «لا توجد تعديلات لحفظها». الاختبار بيثبت إن الفتح والحفظ ماشيين على حد التركيبة.
vi.mock("@/applications/apparel/api/useCatalogWrite", () => ({
  useWarehouses: () => ({ data: [{ id: "w-1", name: "المخزن", is_active: true }] }),
}));
vi.mock("@/applications/apparel/api/useStock", () => ({
  useStockSeasons: () => ({ data: [] }),
  useStockMaterials: () => ({ data: [] }),
}));
vi.mock("@/applications/apparel/api/useShopOptions", () => ({ useShopOptions: () => ({ options: [] }) }));
vi.mock("@/applications/apparel/api/useCatalogList", () => ({
  useNextSkuBase: () => ({ data: null }),
  useExistingSkus: () => ({ data: [] }),
}));

import { planProductEdit } from "@/applications/apparel/api/productEdit";

const product = {
  id: "p-1",
  title: "تجربة تيشيرت قطن",
  slug: "tee",
  status: "active",
  sellPrice: "300.00",
  threshold: 0,
  variants: [
    { id: "v-1", color: "أسود", size: "M", sku: "SKU-1", barcode: null, sellPrice: "300.00", reorderLevel: 5 },
    { id: "v-2", color: "أسود", size: "L", sku: "SKU-2", barcode: null, sellPrice: "300.00", reorderLevel: 5 },
  ],
  images: [],
};

describe("the alert level reaches the saved variants", () => {
  it("turns a product-level change into a reorder change for every variant", () => {
    const before = { ...product, variants: product.variants.map((v) => ({ ...v, reorderLevel: 0 })) };
    const after = { ...product, threshold: "5", variants: product.variants.map((v) => ({ ...v, reorderLevel: "5" })) };
    const plan = planProductEdit(before, after);
    expect(plan.empty).toBe(false);
    expect(plan.reorderChanges).toEqual([
      { id: "v-1", level: 5 },
      { id: "v-2", level: 5 },
    ]);
  });

  it("says there is nothing to save when the level did not actually change", () => {
    const same = { ...product, threshold: "5", variants: product.variants.map((v) => ({ ...v, reorderLevel: "5" })) };
    const plan = planProductEdit(same, same);
    expect(plan.reorderChanges).toEqual([]);
    expect(plan.empty).toBe(true);
  });
});
