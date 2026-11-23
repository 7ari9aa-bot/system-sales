import { describe, expect, it, vi } from "vitest";

const calls = [];
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    calls.push({ path, method: opts.method ?? "GET", body: opts.body });
    if (path === "/warehouses") {
      return [
        { id: "w-main", name: "المخزن الرئيسي", is_active: true },
        { id: "w-branch", name: "فرع مدينة نصر", is_active: true },
      ];
    }
    if (path === "/products/intake") return { product: { id: "p1" }, variants: [] };
    return { ok: true };
  }),
}));

import { catalogApi } from "./catalogApi";
import { defaultWarehouseId } from "./useCatalogWrite";

const product = (warehouseId) => ({
  name: "تيشيرت قطن",
  variants: [{ id: "row-1", color: "أسود", size: "M", sku: "SKU-0001-0101", sellPrice: 300, stock: 5 }],
  warehouseId,
});

describe("the opening balance lands in the warehouse the shop chose", () => {
  it("defaults to the first active warehouse when nothing is chosen", async () => {
    expect(await defaultWarehouseId()).toBe("w-main");
  });

  it("posts the chosen warehouse, not the first one", async () => {
    calls.length = 0;
    await catalogApi.createProduct(product("w-branch"), { warehouseId: "w-branch" });
    const intake = calls.find((c) => c.path === "/products/intake");
    expect(intake.body.warehouse_id).toBe("w-branch");
  });
});
