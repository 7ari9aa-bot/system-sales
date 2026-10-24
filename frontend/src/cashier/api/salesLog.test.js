import { describe, expect, it } from "vitest";
import { dayOf, filterRows, rowFromDetail, saleReceipts, totalsOf } from "./salesLog";
import { statusOf } from "./receiptAdapter";

const detail = (over = {}) => ({
  receipt: { id: "r1", number: "POS-20261020-AAA", kind: "sale", issued_at: "2026-10-20T09:20:07+00:00", tendered_amount: "400.00", change_amount: "100.00" },
  order: { id: "o1", number: "ORD-1", grand_total: "590.00", discount_total: "0.00", fully_returned: false },
  lines: [
    { variant_id: "v1", title: "قميص", sku: "SH-1", quantity: 2, unit_price: "120.00", total: "240.00", returned_qty: 0 },
    { variant_id: "v2", title: "جينز", sku: "JE-1", quantity: 1, unit_price: "350.00", total: "350.00", returned_qty: 0 },
  ],
  tenders: [{ method: "cash", amount: "300.00", status: "captured" }, { method: "card", amount: "290.00", status: "captured" }],
  ...over,
});

describe("saleReceipts", () => {
  it("keeps sales and drops refund/return receipts", () => {
    expect(saleReceipts([{ kind: "sale" }, { kind: "refund" }, { kind: "return" }, { kind: "sale" }])).toHaveLength(2);
  });
});

describe("rowFromDetail", () => {
  it("takes total, pieces and payment from the server's receipt", () => {
    const r = rowFromDetail(detail());
    expect(r).toMatchObject({ number: "POS-20261020-AAA", total: 590, pieces: 3, payment: "mixed", status: "paid" });
    expect(r.paymentLabel).toBe("نقدي + بطاقة");
  });
  it("a sale recorded with no payment has NO payment method (never an invented cash)", () => {
    expect(rowFromDetail(detail({ tenders: [] })).payment).toBeNull();
  });
  it("a single tender keeps its own method", () => {
    expect(rowFromDetail(detail({ tenders: [{ method: "card", amount: "590.00", status: "captured" }] })).payment).toBe("card");
  });
  it("carries the cashier only when it is known", () => {
    expect(rowFromDetail(detail(), { cashier: "منى" }).receipt.cashier).toBe("منى");
    expect(rowFromDetail(detail()).receipt.cashier).toBe("");
  });
  it("never invents a customer", () => {
    const r = rowFromDetail(detail());
    expect(r).not.toHaveProperty("customerName");
  });
});

describe("status comes from what was really returned", () => {
  const items = (q1, q2) => [{ returnedQty: q1 }, { returnedQty: q2 }];
  it("nothing returned -> paid", () => expect(statusOf({ fully_returned: false }, items(0, 0))).toBe("paid"));
  it("some units returned -> partial_return", () => expect(statusOf({ fully_returned: false }, items(1, 0))).toBe("partial_return"));
  it("the server says fully returned -> returned", () => expect(statusOf({ fully_returned: true }, items(2, 1))).toBe("returned"));
});

describe("filterRows / totalsOf", () => {
  const rows = [
    rowFromDetail(detail()),
    rowFromDetail(detail({ receipt: { id: "r2", number: "POS-20261019-BBB", kind: "sale", issued_at: "2026-10-19T10:00:00+00:00", tendered_amount: "590.00", change_amount: "0.00" }, tenders: [{ method: "card", amount: "590.00", status: "captured" }] })),
  ];
  it("filters by day range inclusive", () => expect(filterRows(rows, { from: "2026-10-20", to: "2026-10-20" })).toHaveLength(1));
  it("each end of the range cuts on its own", () => {
    expect(filterRows(rows, { from: "2026-10-20" }).map((r) => dayOf(r.date))).toEqual(["2026-10-20"]);
    expect(filterRows(rows, { to: "2026-10-19" }).map((r) => dayOf(r.date))).toEqual(["2026-10-19"]);
    expect(filterRows(rows, { from: "2026-10-21" })).toHaveLength(0);
  });
  it("no longer filters by payment method (the app does not model it)", () => expect(filterRows(rows, { payment: "card" })).toHaveLength(rows.length));
  it("searches by number or by item code/name", () => {
    expect(filterRows(rows, { term: "bbb" })).toHaveLength(1);
    expect(filterRows(rows, { term: "je-1" })).toHaveLength(2);
    expect(filterRows(rows, { term: "جينز" })).toHaveLength(2);
    expect(filterRows(rows, { term: "zzz" })).toHaveLength(0);
  });
  it("totals add exactly", () => expect(totalsOf(rows)).toEqual({ total: 1180, pieces: 6 }));
  it("empty list totals zero", () => expect(totalsOf([])).toEqual({ total: 0, pieces: 0 }));
});
