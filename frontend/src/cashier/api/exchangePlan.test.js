import { describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { newIntent, posApi } from "./posApi";
import { setQty, returnableLines } from "./returnPlan";
import { differenceMinor, exchangeErrorMessage, exchangePayment, exchangeRequest, needsPayment, sendExchange, settlementKind } from "./exchangePlan";

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

describe("exchangePayment", () => {
  it("no payment needed (and none sent) when the customer is owed money", () => expect(exchangePayment(-500, [])).toEqual({ ok: true, tenders: undefined, tenderedCash: undefined }));
  it("pays the difference in cash with change", () => {
    const p = exchangePayment(18667, [{ method: "cash", amount: "200.00" }]);
    expect(p).toMatchObject({ ok: true, tenders: [{ method: "cash", amount: "186.67" }], tenderedCash: "200.00" });
  });
  it("refuses a short payment", () => expect(exchangePayment(18667, [{ method: "cash", amount: "100.00" }])).toMatchObject({ ok: false, remaining: "86.67" }));
});

describe("exchangeRequest", () => {
  it("needs something to return and something to replace it with", () => {
    expect(() => exchangeRequest(sale, back(0), repl)).toThrow();
    expect(() => exchangeRequest(sale, back(1), [])).toThrow();
  });
  it("is accepted by the real posApi.exchange and posted as the backend expects", async () => {
    const req = exchangeRequest(sale, back(1), repl, { restock: false, tenders: [{ method: "cash", amount: "186.67" }], tenderedCash: "200.00" });
    await posApi.exchange("sess-1", req, newIntent());
    const [path, opts] = api.mock.calls.at(-1);
    expect(path).toBe("/pos/sessions/sess-1/exchanges");
    expect(opts.body).toEqual({
      order_id: "o1",
      return_lines: [{ variant_id: "v1", quantity: 1 }],
      new_lines: [{ variant_id: "n1", quantity: 2 }],
      restock: false,
      tenders: [{ method: "cash", amount: "186.67" }],
      tendered_cash: "200.00",
    });
    expect(opts.headers["Idempotency-Key"]).toMatch(/^pos-/);
  });
  it("a refund exchange sends no tenders at all", async () => {
    await posApi.exchange("s", exchangeRequest(sale, back(3), repl), newIntent());
    const body = api.mock.calls.at(-1)[1].body;
    expect("tenders" in body).toBe(false);
  });
});

describe("exchangeErrorMessage", () => {
  it("maps the known refusals", () => {
    expect(exchangeErrorMessage(new Error("tenders total 10 but the exchange difference is 12"))).toMatch(/فرق الاستبدال/);
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
  it("does not retry a real refusal (underpaid difference)", async () => {
    const send = vi.fn().mockRejectedValue(new Error("tenders total 100.00 but the exchange difference is 230.00"));
    await expect(sendExchange(send, { sleep: async () => {} })).rejects.toThrow(/difference/);
    expect(send).toHaveBeenCalledTimes(1);
  });
});

describe("needsPayment", () => {
  const paid = { tenders: [{ method: "cash", amount: "100.00" }] };

  it("never asks for money, even when the customer owes a difference on an old paid sale", () => {
    expect(needsPayment(paid, 5000)).toBe(false);
    expect(needsPayment({ tenders: [] }, 5000)).toBe(false);
    expect(needsPayment(undefined, 5000)).toBe(false);
    expect(needsPayment(paid, 0)).toBe(false);
    expect(needsPayment(paid, -4000)).toBe(false);
  });
});
