import { beforeEach, describe, expect, it, vi } from "vitest";

const { pos } = vi.hoisted(() => ({ pos: { quote: vi.fn(), sell: vi.fn() } }));
vi.mock("./posApi", async () => ({ posApi: pos, newIntent: (await vi.importActual("./posApi")).newIntent }));

import { createSaleSession } from "./saleSession";

const cart = [{ variantId: "v1", qty: 2 }];
const pay = { total: "50.00", cart, tenders: [{ method: "cash", amount: "50" }] };
beforeEach(() => vi.clearAllMocks());

describe("createSaleSession: one payment intent = one Idempotency-Key", () => {
  it("a retry of the SAME payment re-sends the SAME key (so the server replays, not re-sells)", async () => {
    pos.sell.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    await sale.pay(pay);
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).toBe(keys[1]);
  });

  it("a double tap while the first request is in flight sends ONE request", async () => {
    let release;
    pos.sell.mockImplementation(() => new Promise((r) => (release = () => r({ receipt_id: "r1" }))));
    const sale = createSaleSession("sess-1");
    const a = sale.pay(pay);
    const b = sale.pay(pay);
    release();
    await Promise.all([a, b]);
    expect(pos.sell).toHaveBeenCalledTimes(1);
  });

  it("changing the cart or the amounts after a failure starts a NEW intent (never replay an old receipt)", async () => {
    pos.sell.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ receipt_id: "r2" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    await sale.pay({ ...pay, cart: [{ variantId: "v1", qty: 3 }], total: "75.00", tenders: [{ method: "cash", amount: "75" }] });
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("after a successful sale the next sale gets a fresh key", async () => {
    pos.sell.mockResolvedValue({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1");
    await sale.pay(pay);
    await sale.pay(pay);
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("an unpaid cart never reaches the backend", async () => {
    const sale = createSaleSession("sess-1");
    await expect(sale.pay({ ...pay, tenders: [{ method: "cash", amount: "10" }] })).rejects.toThrow();
    expect(pos.sell).not.toHaveBeenCalled();
  });

  it("sends the cashier's exact payload (cart, trimmed tenders, tendered cash) to /sell", async () => {
    pos.sell.mockResolvedValue({ receipt_id: "r1" });
    await createSaleSession("sess-1").pay({ ...pay, total: "42.50", discountTotal: "7.50", tenders: [{ method: "cash", amount: "50" }] });
    const [sessionId, body] = pos.sell.mock.calls[0];
    expect(sessionId).toBe("sess-1");
    expect(body).toMatchObject({ items: [{ variant_id: "v1", quantity: 2 }], tenders: [{ method: "cash", amount: "42.50" }], tenderedCash: "50.00", discountTotal: "7.50" });
  });
});

describe("quote", () => {
  it("asks the backend for the total instead of computing it", async () => {
    pos.quote.mockResolvedValue({ subtotal: "50.00", discount_total: "7.50", grand_total: "42.50" });
    const q = await createSaleSession("sess-1").quote({ cart, discountTotal: "7.50" });
    expect(q.total).toBe("42.50");
    expect(pos.quote).toHaveBeenCalledWith("sess-1", { items: [{ variant_id: "v1", quantity: 2 }], discountTotal: "7.50" });
  });
  it("an empty cart has a zero total without calling the backend", async () => {
    const q = await createSaleSession("sess-1").quote({ cart: [] });
    expect(q.total).toBe("0.00");
    expect(pos.quote).not.toHaveBeenCalled();
  });
});
