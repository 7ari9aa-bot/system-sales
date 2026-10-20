import { beforeEach, describe, expect, it, vi } from "vitest";

let balanceRows = [];
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path) => {
    if (path.startsWith("/inventory/balances")) return balanceRows;
    if (path.startsWith("/products")) return [];
    return {};
  }),
}));

import { BALANCES_LIMIT, posApi } from "./posApi";
import { fetchCatalog } from "./usePosSale";
import { api } from "@/lib/api";

beforeEach(() => {
  balanceRows = [];
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
