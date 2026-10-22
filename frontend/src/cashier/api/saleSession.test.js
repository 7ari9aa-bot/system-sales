import { beforeEach, describe, expect, it, vi } from "vitest";

const { pos } = vi.hoisted(() => ({ pos: { quote: vi.fn(), sell: vi.fn(), recordSale: vi.fn(), receipt: vi.fn() } }));
vi.mock("./posApi", async () => {
  const real = await vi.importActual("./posApi");
  return { posApi: pos, newIntent: real.newIntent };
});

import { createSaleSession } from "./saleSession";

const cart = [{ variantId: "v1", qty: 2 }];
const pay = { total: "50.00", cart, tenders: [{ method: "cash", amount: "50" }] };
beforeEach(() => {
  vi.clearAllMocks();
  pos.receipt.mockResolvedValue({ id: "r" });
});

describe("createSaleSession: one payment intent = one Idempotency-Key", () => {
  it("a retry of the SAME payment re-sends the SAME key (so the server replays, not re-sells)", async () => {
    pos.sell.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    await sale.pay(pay);
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).toBe(keys[1]);
  });

  it("changing ONLY a line's own discount is a different payment: new key (the server would replay the old receipt)", async () => {
    pos.sell.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1");
    const withPct = (discountPct) => ({ ...pay, cart: [{ variantId: "v1", qty: 2, discountPct }] });
    await expect(sale.pay(withPct(10))).rejects.toThrow();
    await sale.pay(withPct(50)); // same item, same quantity, same totals typed: only the line discount differs
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).not.toBe(keys[1]);
  });

  it("sale OK but receipt read FAILS: the retry re-sends the SAME key (one sale, not two)", async () => {
    pos.sell.mockResolvedValue({ receipt_id: "r1" });
    pos.receipt.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ id: "r1" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    const out = await sale.pay(pay);
    const keys = pos.sell.mock.calls.map((c) => c[2].key);
    expect(keys[0]).toBe(keys[1]);
    expect(out.detail).toEqual({ id: "r1" });
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

describe("a failed sale and the idempotency key", () => {
  it("a retry of the SAME cart re-sends the same key (the server replays, never double-charges)", async () => {
    pos.sell.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    await sale.pay(pay);
    const [first, second] = pos.sell.mock.calls.map((c) => c[2]);
    expect(second.key).toBe(first.key);
  });

  it("a CHANGED cart after a failure is a new sale: new key", async () => {
    pos.sell.mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce({ receipt_id: "r2" });
    const sale = createSaleSession("sess-1");
    await expect(sale.pay(pay)).rejects.toThrow();
    await sale.pay({ ...pay, cart: [{ variantId: "v1", qty: 3 }], total: "75.00", tenders: [{ method: "cash", amount: "75" }] });
    const [first, second] = pos.sell.mock.calls.map((c) => c[2]);
    expect(second.key).not.toBe(first.key);
  });
});

describe("confirm: a sale is recorded, never paid", () => {
  const sale0 = { cart, customerId: "c1" };
  beforeEach(() => {
    pos.recordSale.mockReset();
    pos.recordSale.mockResolvedValue({ receipt_id: "r1" });
  });

  it("goes to the register's /sales route with items and customer, and NO payment field", async () => {
    const sale = createSaleSession("sess-1", "reg-1");
    const out = await sale.confirm({ ...sale0, discountTotal: "5.00" });
    expect(pos.sell).not.toHaveBeenCalled();
    const [registerId, payload] = pos.recordSale.mock.calls[0];
    expect(registerId).toBe("reg-1");
    expect(payload).toEqual({ items: [{ variant_id: "v1", quantity: 2 }], customerId: "c1", discountTotal: "5.00" });
    for (const k of ["tenders", "method", "amount", "tenderedCash"]) expect(payload).not.toHaveProperty(k);
    expect(out.detail).toEqual({ id: "r" });
  });

  it("a retry of the SAME cart re-sends the SAME key; a changed cart gets a new one", async () => {
    pos.recordSale.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1", "reg-1");
    await expect(sale.confirm(sale0)).rejects.toThrow();
    await sale.confirm(sale0);
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(keys[0]).toBe(keys[1]);

    // The retry succeeded, so the key was released; a failed attempt on a DIFFERENT cart is a new intent.
    pos.recordSale.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 }));
    await expect(sale.confirm({ ...sale0, cart: [{ variantId: "v1", qty: 3 }] })).rejects.toThrow();
    pos.recordSale.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 }));
    await expect(sale.confirm({ ...sale0, cart: [{ variantId: "v1", qty: 4 }] })).rejects.toThrow();
    const calls = pos.recordSale.mock.calls;
    expect(calls).toHaveLength(4);
    expect(calls[3][2].key).not.toBe(calls[2][2].key);
  });

  it("the invoice note travels with the sale, and is left out when there is none", async () => {
    const sale = createSaleSession("sess-1", "reg-1");
    await sale.confirm({ ...sale0, note: "هدية" });
    await sale.confirm(sale0);
    expect(pos.recordSale.mock.calls[0][1].note).toBe("هدية");
    expect(pos.recordSale.mock.calls[1][1].note).toBeUndefined();
  });

  it("another note after a failure is a different invoice (new key); the same note replays the same key", async () => {
    const down = () => Object.assign(new Error("network"), { status: 0 });
    pos.recordSale.mockRejectedValueOnce(down()).mockRejectedValueOnce(down()).mockRejectedValueOnce(down());
    const sale = createSaleSession("sess-1", "reg-1");
    await expect(sale.confirm({ ...sale0, note: "a" })).rejects.toThrow();
    await expect(sale.confirm({ ...sale0, note: "a" })).rejects.toThrow();
    await expect(sale.confirm({ ...sale0, note: "b" })).rejects.toThrow();
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("a double tap sends ONE request, and an empty cart never reaches the backend", async () => {
    let release;
    pos.recordSale.mockImplementation(() => new Promise((r) => (release = () => r({ receipt_id: "r1" }))));
    const sale = createSaleSession("sess-1", "reg-1");
    const a = sale.confirm(sale0);
    const b = sale.confirm(sale0);
    release();
    await Promise.all([a, b]);
    expect(pos.recordSale).toHaveBeenCalledTimes(1);
    await expect(sale.confirm({ cart: [] })).rejects.toThrow(/empty/i);
  });

  it("a line's own discount makes it a different sale (new key)", async () => {
    pos.recordSale.mockRejectedValueOnce(Object.assign(new Error("network"), { status: 0 })).mockResolvedValueOnce({ receipt_id: "r1" });
    const sale = createSaleSession("sess-1", "reg-1");
    const withPct = (discountPct) => ({ ...sale0, cart: [{ variantId: "v1", qty: 2, discountPct }] });
    await expect(sale.confirm(withPct(10))).rejects.toThrow();
    await sale.confirm(withPct(50));
    const keys = pos.recordSale.mock.calls.map((c) => c[2].key);
    expect(keys[0]).not.toBe(keys[1]);
  });
});
