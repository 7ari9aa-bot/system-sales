import { describe, expect, it, vi } from "vitest";
import { newIntent, posApi } from "./posApi";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ ok: true })) }));
import { api } from "@/lib/api";
import { sendReturn, tableLine, estimateRefund, estimateRefundMinor, returnErrorMessage, returnRequest, returnableLines, setQty } from "./returnPlan";

const sale = (over = {}) => ({
  order: { id: "o1", grand_total: "340.00", discount_total: "20.00" },
  lines: [{ variant_id: "v1", title: "قميص", sku: "SH-1", quantity: 3, unit_price: "120.00", total: "360.00", returned_qty: 0 }],
  ...over,
});

describe("returnableLines", () => {
  it("max = sold - already returned", () => {
    const l = returnableLines(sale({ lines: [{ variant_id: "v1", title: "x", quantity: 3, unit_price: "10.00", returned_qty: 2 }] }));
    expect(l[0]).toMatchObject({ sold: 3, alreadyReturned: 2, maxQty: 1, returnQty: 0 });
  });
  it("fully returned line has nothing left", () => {
    expect(returnableLines(sale({ lines: [{ variant_id: "v", quantity: 1, unit_price: "5.00", returned_qty: 1 }] }))[0].maxQty).toBe(0);
  });
  it("never goes negative", () => {
    expect(returnableLines(sale({ lines: [{ variant_id: "v", quantity: 1, unit_price: "5.00", returned_qty: 9 }] }))[0].maxQty).toBe(0);
  });
});

describe("setQty", () => {
  const base = returnableLines(sale());
  it("clamps to the available quantity", () => expect(setQty(base, "v1", 99)[0].returnQty).toBe(3));
  it("clamps below zero and garbage to 0", () => {
    expect(setQty(base, "v1", -4)[0].returnQty).toBe(0);
    expect(setQty(base, "v1", "abc")[0].returnQty).toBe(0);
    expect(setQty(base, "v1", 1.9)[0].returnQty).toBe(1);
  });
  it("touches only its own line", () => {
    const two = returnableLines(sale({ lines: [{ variant_id: "a", quantity: 2, unit_price: "1.00" }, { variant_id: "b", quantity: 2, unit_price: "1.00" }] }));
    const r = setQty(two, "a", 2);
    expect([r[0].returnQty, r[1].returnQty]).toEqual([2, 0]);
  });
});

describe("estimateRefund follows the backend's proportional-discount rule", () => {
  const withQty = (s, q) => setQty(returnableLines(s), "v1", q);
  it("no discount -> plain price", () => {
    const s = sale({ order: { id: "o", discount_total: "0.00" } });
    expect(estimateRefund(s, withQty(s, 2))).toBe("240.00");
  });
  it("discount 20 on 360 subtotal: 1 unit refunds 120 - 6.67 = 113.33", () => {
    const s = sale();
    expect(estimateRefund(s, withQty(s, 1))).toBe("113.33");
  });
  it("returning everything refunds exactly the amount paid (360 - 20)", () => {
    const s = sale();
    expect(estimateRefund(s, withQty(s, 3))).toBe("340.00");
  });
  it("nothing selected -> 0", () => expect(estimateRefundMinor(sale(), returnableLines(sale()))).toBe(0));
  it("rounds half up per line like the backend", () => {
    // 10.00 x1 line, subtotal 30.00 (3 lines of 10), discount 1.00 -> share 0.3333 -> 0.33 ; refund 9.67
    const s = { order: { id: "o", discount_total: "1.00" }, lines: [{ variant_id: "v1", quantity: 1, unit_price: "10.00" }, { variant_id: "v2", quantity: 2, unit_price: "10.00" }] };
    expect(estimateRefund(s, setQty(returnableLines(s), "v1", 1))).toBe("9.67");
  });
});

describe("returnRequest", () => {
  it("sends only picked lines and the restock choice", () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 2), { restock: true });
    expect(req).toEqual({ orderId: "o1", lines: [{ variant_id: "v1", quantity: 2 }], restock: true });
  });
  it("restock defaults to an explicit boolean", () => {
    const s = sale();
    expect(returnRequest(s, setQty(returnableLines(s), "v1", 1), {}).restock).toBe(false);
  });
  it("refuses an empty return", () => {
    expect(() => returnRequest(sale(), returnableLines(sale()), { restock: false })).toThrow();
  });
});

describe("returnErrorMessage", () => {
  it("explains the different-session rule", () => expect(returnErrorMessage(new Error("this sale belongs to a different session"))).toMatch(/وردية أخرى/));
  it("explains a closed shift", () => expect(returnErrorMessage(new Error("this session is closed; returns ride the open drawer"))).toMatch(/مغلقة/));
  it("never hides an unknown error", () => expect(returnErrorMessage(new Error("boom 42"))).toBe("boom 42"));
});

describe("tableLine", () => {
  it("keeps the picked quantity and adds what the tables read", () => {
    const l = tableLine({ ...returnableLines(sale())[0], returnQty: 2 });
    expect(l).toMatchObject({ key: "v1", barcode: "SH-1", qty: 3, unitNet: 120, total: 360, returnQty: 2, maxQty: 3 });
  });
  it("does not invent size or colour", () => {
    const l = tableLine(returnableLines(sale())[0]);
    expect([l.size, l.color]).toEqual(["", ""]);
  });
});

describe("a planned return is accepted by the real posApi.returnSale (contract)", () => {
  it("builds a request the client sends as-is to /returns", async () => {
    const s = sale();
    const req = returnRequest(s, setQty(returnableLines(s), "v1", 2), { restock: false });
    await posApi.returnSale("sess-1", req, newIntent());
    const [path, opts] = api.mock.calls.at(-1);
    expect(path).toBe("/pos/sessions/sess-1/returns");
    expect(opts.body).toEqual({ order_id: "o1", lines: [{ variant_id: "v1", quantity: 2 }], restock: false });
    expect(opts.headers["Idempotency-Key"]).toMatch(/^pos-/);
  });
});

describe("sendReturn", () => {
  const noWait = { sleep: async () => {} };
  it("passes a normal success through, one call", async () => {
    const send = vi.fn(async () => ({ ok: 1 }));
    expect(await sendReturn(send, noWait)).toEqual({ ok: 1 });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("retries while the same intent is in progress, then returns the replayed answer", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("request with this Idempotency-Key is in progress")).mockResolvedValueOnce({ n: "POS-RET-1" });
    expect(await sendReturn(send, noWait)).toEqual({ n: "POS-RET-1" });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it("gives up after the tries and surfaces the error", async () => {
    const send = vi.fn().mockRejectedValue(new Error("request with this Idempotency-Key is in progress"));
    await expect(sendReturn(send, { ...noWait, tries: 3 })).rejects.toThrow(/in progress/);
    expect(send).toHaveBeenCalledTimes(3);
  });
  it("does NOT retry a real refusal", async () => {
    const send = vi.fn().mockRejectedValue(new Error("this sale belongs to a different session"));
    await expect(sendReturn(send, noWait)).rejects.toThrow(/different session/);
    expect(send).toHaveBeenCalledTimes(1);
  });
});

describe("estimateRefundMinor with per-item discounts (report example)", () => {
  // A: 100 at 50% off = 50 paid. B: 100 no discount. Invoice total 150.
  const sale = (extra = {}) => ({
    order: { discount_total: "50.00", grand_total: "150.00", ...extra },
    lines: [
      { variant_id: "A", title: "A", quantity: 1, unit_price: "100.00", discount_pct: "50.00", returned_qty: 0 },
      { variant_id: "B", title: "B", quantity: 1, unit_price: "100.00", discount_pct: "0.00", returned_qty: 0 },
    ],
  });
  const pick = (d, id, qty) => returnableLines(d).map((l) => (l.variantId === id ? { ...l, returnQty: qty } : l));

  it("returning the 50%-off item refunds 50, not 75 or 100", () => {
    const d = sale();
    expect(estimateRefund(d, pick(d, "A", 1))).toBe("50.00");
  });
  it("returning the full-price item refunds 100", () => {
    const d = sale();
    expect(estimateRefund(d, pick(d, "B", 1))).toBe("100.00");
  });
  it("exchange difference: A (50 paid) swapped for a 60 item is +10", () => {
    const d = sale();
    expect(Number(estimateRefund(d, pick(d, "A", 1))) - 60).toBe(-10);
  });
  it("an invoice-level discount on top is shared over the NET of the lines, per the backend", () => {
    // gross 200, A has 50% off (net 150). Invoice discount 15 beyond the line discount.
    const d = sale({ discount_total: "65.00" });
    // order_level = 65 - (200-150) = 15 ; A net 50 -> share 15*50/150 = 5.00 -> refund 45.00
    expect(estimateRefund(d, pick(d, "A", 1))).toBe("45.00");
  });
  it("partial quantity rounds half up to cents", () => {
    const d = { order: { discount_total: "0.00" }, lines: [{ variant_id: "C", title: "C", quantity: 3, unit_price: "33.33", discount_pct: "0.00", returned_qty: 0 }] };
    expect(estimateRefund(d, pick(d, "C", 2))).toBe("66.66");
  });
});
