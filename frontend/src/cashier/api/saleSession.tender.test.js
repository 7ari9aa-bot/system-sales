import { beforeEach, describe, expect, it, vi } from "vitest";

const { pos } = vi.hoisted(() => ({ pos: { quote: vi.fn(), recordSale: vi.fn(), receipt: vi.fn() } }));
vi.mock("./posApi", async () => {
  const real = await vi.importActual("./posApi");
  return { posApi: pos, newIntent: real.newIntent };
});

import { createSaleSession } from "./saleSession";

const cart = [{ variantId: "v1", qty: 2 }];
const cash = [{ method: "cash", amount: "100.00" }];
const card = [{ method: "card", amount: "100.00", reference: "77" }];
const down = () => Object.assign(new Error("network"), { status: 0 });

beforeEach(() => {
  vi.clearAllMocks();
  pos.receipt.mockResolvedValue({ id: "r" });
  pos.recordSale.mockReset();
  pos.recordSale.mockResolvedValue({ receipt_id: "r1" });
});

describe("a sale on a till that records payments", () => {
  it("sends the payment lines and the on-account flag with the sale", async () => {
    const sale = createSaleSession("s", "reg");
    await sale.confirm({ cart, customerId: "c1", payments: cash, onAccount: true });
    const payload = pos.recordSale.mock.calls[0][1];
    expect(payload.payments).toEqual(cash);
    expect(payload.onAccount).toBe(true);
  });

  it("sends neither when the till does not record payments", async () => {
    const sale = createSaleSession("s", "reg");
    await sale.confirm({ cart, customerId: "c1" });
    const payload = pos.recordSale.mock.calls[0][1];
    expect(payload.payments).toBeUndefined();
    expect(payload.onAccount).toBeUndefined();
  });

  it("another way of paying is another sale: a retry never replays the old payment under the same key", async () => {
    pos.recordSale.mockRejectedValueOnce(down()).mockRejectedValueOnce(down()).mockRejectedValueOnce(down());
    const sale = createSaleSession("s", "reg");
    await expect(sale.confirm({ cart, payments: cash })).rejects.toThrow();
    await expect(sale.confirm({ cart, payments: cash })).rejects.toThrow();
    await expect(sale.confirm({ cart, payments: card })).rejects.toThrow();
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("paying part and putting the rest on account is another sale than paying it all", async () => {
    pos.recordSale.mockRejectedValueOnce(down()).mockRejectedValueOnce(down());
    const sale = createSaleSession("s", "reg");
    await expect(sale.confirm({ cart, customerId: "c1", payments: cash })).rejects.toThrow();
    await expect(sale.confirm({ cart, customerId: "c1", payments: cash, onAccount: true })).rejects.toThrow();
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(keys[1]).not.toBe(keys[0]);
  });

  it("a different amount or reference on the same method is another sale", async () => {
    pos.recordSale.mockRejectedValue(down());
    const sale = createSaleSession("s", "reg");
    for (const payments of [card, [{ ...card[0], reference: "78" }], [{ ...card[0], amount: "90.00" }]]) {
      await expect(sale.confirm({ cart, payments })).rejects.toThrow();
    }
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(new Set(keys).size).toBe(3);
  });
});
