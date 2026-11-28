import { describe, expect, it, vi, beforeEach } from "vitest";

const createProduct = vi.fn();
const moveStock = vi.fn();
vi.mock("./catalogApi", () => ({
  catalogApi: {
    createProduct: (...args) => createProduct(...args),
    moveStock: (...args) => moveStock(...args),
  },
}));

import { saveProductWithDistribution } from "./useCatalogWrite";

const shops = [
  { id: "w-shop", name: "المحل", is_active: true },
  { id: "w-store", name: "المخزن", is_active: true },
];
const base = {
  name: "تيشيرت",
  warehouses: shops,
  variants: [{ id: "r1", sku: "SKU-1", color: "أسود", size: "M", sellPrice: "300", stock: 40, alloc: { "w-store": 30 } }],
};

describe("creating a product with the balance split over warehouses", () => {
  beforeEach(() => {
    createProduct.mockReset();
    moveStock.mockReset();
  });

  it("sends the shop's share to intake and one movement for the warehouse share", async () => {
    createProduct.mockResolvedValue({ product: { id: "p-1" }, variants: [{ id: "v-1", sku: "SKU-1" }] });
    moveStock.mockResolvedValue({ id: "mv-1" });

    await saveProductWithDistribution(base, "w-shop");

    const [payload, opts] = createProduct.mock.calls[0];
    expect(opts.warehouseId).toBe("w-shop");
    expect(payload.variants[0].stock).toBe(10);
    expect(moveStock).toHaveBeenCalledWith({ variantId: "v-1", warehouseId: "w-store", direction: "in", quantity: 30, reason: "adjustment" });
  });

  it("keeps the product saved and reports the warehouse that failed", async () => {
    createProduct.mockResolvedValue({ product: { id: "p-1" }, variants: [{ id: "v-1", sku: "SKU-1" }] });
    moveStock.mockRejectedValue(new Error("المخزن مقفول"));

    const created = await saveProductWithDistribution(base, "w-shop");

    expect(created.product.id).toBe("p-1");
    expect(created.distribution.failed).toHaveLength(1);
    expect(created.distribution.failed[0]).toMatchObject({ warehouseId: "w-store", quantity: 30, message: "المخزن مقفول" });
  });

  it("does not move anything when the whole balance stays in one warehouse", async () => {
    createProduct.mockResolvedValue({ product: { id: "p-1" }, variants: [{ id: "v-1", sku: "SKU-1" }] });

    await saveProductWithDistribution({ ...base, variants: [{ ...base.variants[0], alloc: {} }] }, "w-shop");

    expect(createProduct.mock.calls[0][0].variants[0].stock).toBe(40);
    expect(moveStock).not.toHaveBeenCalled();
  });
});
