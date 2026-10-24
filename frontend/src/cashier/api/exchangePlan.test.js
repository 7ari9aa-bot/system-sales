import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { newIntent, posApi } from "./posApi";
import { setQty, returnableLines } from "./returnPlan";
import { differenceMinor, exchangeErrorMessage, exchangeRequest, sendExchange, settlementKind } from "./exchangePlan";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ ok: true })) }));

const sale = {
  order: { id: "o1", discount_total: "20.00" },
  lines: [{ variant_id: "v1", title: "قميص", sku: "SH", quantity: 3, unit_price: "120.00", returned_qty: 0 }],
};
const back = (q) => setQty(returnableLines(sale), "v1", q);
const repl = [{ variantId: "n1", qty: 2 }];

describe("difference", () => {
  it("replacement 300 vs 1 unit back (113.33) -> customer pays 186.67", () => expect(differenceMinor(sale, back(1), "300.00")).toBe(18667));
  it("replacement cheaper than the return -> negative (refund)", () => expect(differenceMinor(sale, back(3), "100.00")).toBe(10000 - 34000));
  it("equal -> 0", () => expect(differenceMinor(sale, back(1), "113.33")).toBe(0));
  it("missing quote counts as 0, never NaN", () => expect(differenceMinor(sale, back(1), undefined)).toBe(-11333));
});

describe("settlementKind", () => {
  it("pay / refund / even", () => expect([settlementKind(5), settlementKind(-5), settlementKind(0)]).toEqual(["pay", "refund", "even"]));
});

describe("exchangeRequest", () => {
  it("needs something to return and something to replace it with", () => {
    expect(() => exchangeRequest(sale, back(0), repl)).toThrow();
    expect(() => exchangeRequest(sale, back(1), [])).toThrow();
  });
  it("is accepted by the real posApi.exchange and posted as the backend expects", async () => {
    const req = exchangeRequest(sale, back(1), repl, { restock: false });
    await posApi.exchange("sess-1", req, newIntent());
    const [path, opts] = api.mock.calls.at(-1);
    expect(path).toBe("/pos/sessions/sess-1/exchanges");
    expect(opts.body).toEqual({
      order_id: "o1",
      return_lines: [{ variant_id: "v1", quantity: 1 }],
      new_lines: [{ variant_id: "n1", quantity: 2 }],
      restock: false,
    });
    expect(opts.headers["Idempotency-Key"]).toMatch(/^pos-/);
  });
  it("never carries a payment field, whatever the difference is", async () => {
    for (const q of [1, 3]) {
      await posApi.exchange("s", exchangeRequest(sale, back(q), repl), newIntent());
      const body = api.mock.calls.at(-1)[1].body;
      for (const k of ["tenders", "tendered_cash", "method", "amount"]) expect(k in body).toBe(false);
    }
  });
});

describe("exchangeErrorMessage", () => {
  it("maps the known refusals", () => {
    expect(exchangeErrorMessage(new Error("insufficient stock for variant"))).toMatch(/المخزون/);
    expect(exchangeErrorMessage(new Error("this session is closed; exchanges ride the open drawer"))).toMatch(/مغلقة/);
  });
  it("never hides an unknown error", () => expect(exchangeErrorMessage(new Error("boom 7"))).toBe("boom 7"));
});

describe("sendExchange", () => {
  it("waits and re-sends the SAME call while the first is in progress, then returns the replayed answer", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("request with this Idempotency-Key is in progress")).mockResolvedValueOnce({ new_receipt_number: "POS-9" });
    expect(await sendExchange(send, { sleep: async () => {} })).toEqual({ new_receipt_number: "POS-9" });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it("does not retry a real refusal (not enough stock)", async () => {
    const send = vi.fn().mockRejectedValue(new Error("insufficient stock for the replacement"));
    await expect(sendExchange(send, { sleep: async () => {} })).rejects.toThrow(/insufficient/);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
