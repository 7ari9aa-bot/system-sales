import { beforeEach, describe, expect, it, vi } from "vitest";

let balanceRows = [];
let productRows = [];
let sessionRows = [];
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path) => {
    if (path.startsWith("/inventory/balances")) return balanceRows;
    if (path.startsWith("/products")) {
      const q = new URLSearchParams(path.split("?")[1]);
      const off = Number(q.get("offset") ?? 0);
      const lim = Number(q.get("limit") ?? productRows.length);
      return productRows.slice(off, off + lim);
    }
    if (path.includes("/items")) {
      const q = new URLSearchParams(path.split("?")[1]);
      const off = Number(q.get("offset") ?? 0);
      const lim = Number(q.get("limit") ?? 60);
      return { items: sessionRows.slice(off, off + lim), total: sessionRows.length };
    }
    return {};
  }),
}));

import { BALANCES_LIMIT, posApi } from "./posApi";
import { fetchCatalog, fetchSessionCatalog } from "./usePosSale";
import { api } from "@/lib/api";

beforeEach(() => {
  balanceRows = [];
  productRows = [];
  sessionRows = [];
  api.mockClear();
});

describe("stock list truncation must never be silent", () => {
  it("asks the backend for a big page (its default is 200 with no ordering)", async () => {
    await posApi.stockBalances();
    expect(api).toHaveBeenCalledWith(`/inventory/balances?limit=${BALANCES_LIMIT}`);
    expect(BALANCES_LIMIT).toBeGreaterThan(200);
  });
  it("loads normally when the list is smaller than the limit", async () => {
    balanceRows = Array.from({ length: 300 }, (_, i) => ({ variant_id: `v${i}`, on_hand: 1, reserved: 0 }));
    await expect(fetchCatalog()).resolves.toEqual([]);
  });
  it("refuses a page exactly as large as the limit (it was probably cut)", async () => {
    balanceRows = Array.from({ length: BALANCES_LIMIT }, (_, i) => ({ variant_id: `v${i}`, on_hand: 1, reserved: 0 }));
    await expect(fetchCatalog()).rejects.toThrow(/وصلت للحد الأقصى/);
  });
});

const product = (i) => ({
  id: `p${i}`,
  title: `Item ${i}`,
  status: "active",
  images: [],
  variants: [{ id: `v${i}`, sku: `S${i}`, barcode: `B${i}`, price: "10.00", is_active: true, option_values: {} }],
});
const sessionItem = (i) => ({ variant_id: `v${i}`, available: 3, unit_price: "12.50" });

describe("the sales screen does not depend on the shop-wide balances", () => {
  it("sells normally when the shop-wide balance list is far past its cap", async () => {
    // 6,000 balance rows would make fetchCatalog() refuse; the sales screen must not even ask.
    balanceRows = Array.from({ length: 6000 }, (_, i) => ({ variant_id: `x${i}`, on_hand: 1, reserved: 0 }));
    productRows = [product(1), product(2)];
    sessionRows = [sessionItem(1), sessionItem(2)];
    const out = await fetchSessionCatalog("s1");
    expect(out.map((v) => v.id)).toEqual(["v1", "v2"]);
    expect(out[0]).toMatchObject({ stock: 3, sellPrice: 12.5, barcode: "B1" }); // the till's own figures
    expect(api.mock.calls.some(([p]) => String(p).startsWith("/inventory/balances"))).toBe(false);
  });

  it("walks every product page: a shop past 500 products loses none of them", async () => {
    productRows = Array.from({ length: 1234 }, (_, i) => product(i));
    sessionRows = [sessionItem(0), sessionItem(700), sessionItem(1233)];
    const out = await fetchSessionCatalog("s1");
    expect(out.map((v) => v.id)).toEqual(["v0", "v700", "v1233"]);
  });
});
