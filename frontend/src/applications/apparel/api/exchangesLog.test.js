import { describe, expect, it } from "vitest";
import { exchangeRows, filterExchanges, settlementOf, summarizeExchanges } from "./exchangesLog";

const list = [
  { id: "s1", kind: "sale", number: "POS-1", order_id: "o1", session_id: "A", issued_at: "2026-10-20T09:00:00Z" },
  { id: "r1", kind: "return", number: "POS-RET-1", order_id: "o1", session_id: "A", issued_at: "2026-10-20T10:00:00Z" },
  { id: "s2", kind: "sale", number: "POS-2", order_id: "o2", session_id: "A", issued_at: "2026-10-20T10:00:01Z", exchange_return_receipt_id: "r1" },
  { id: "s3", kind: "sale", number: "POS-3", order_id: "o3", session_id: "B", issued_at: "2026-10-19T09:00:00Z" },
  { id: "r9", kind: "return", number: "POS-RET-9", order_id: "o3", session_id: "B", issued_at: "2026-10-19T12:00:00Z" },
  { id: "s4", kind: "sale", number: "POS-4", order_id: "o4", session_id: "B", issued_at: "2026-10-19T12:00:01Z", exchange_return_receipt_id: "r9" },
];
const details = {
  r1: { lines: [{ title: "قميص", quantity: 1, total: "25.00" }] },
  s2: { lines: [{ title: "بنطلون", quantity: 1 }], order: { grand_total: "40.00" } },
  r9: { lines: [{ title: "حذاء", quantity: 1, total: "100.00" }] },
  s4: { lines: [{ title: "شبشب", quantity: 2 }], order: { grand_total: "60.00" } },
};

describe("exchangeRows", () => {
  it("an exchange is exactly a sale receipt carrying the stored link; plain sales and returns are not", () => {
    expect(exchangeRows(list, details).map((r) => r.number)).toEqual(["POS-2", "POS-4"]);
  });
  it("a return followed by an UNLINKED sale (old data) is not guessed into an exchange", () => {
    const old = list.filter((r) => r.id !== "s2");
    expect(exchangeRows(old, details).map((r) => r.number)).toEqual(["POS-4"]);
  });
  it("pairs each with the ORIGINAL invoice, the return receipt, the items and both values", () => {
    const r = exchangeRows(list, details).find((x) => x.number === "POS-2");
    expect(r).toMatchObject({ invoiceNumber: "POS-1", invoiceId: "s1", returnReceiptNumber: "POS-RET-1", returnedItem: "قميص", newItem: "بنطلون", returnedValue: 25, newValue: 40 });
  });
  it("an unknown original shows a dash, not a guess", () => {
    const r = exchangeRows([list[2]], details)[0];
    expect(r.invoiceNumber).toBe("—");
  });
  it("the new sale is never mistaken for the original invoice of the same order", () => {
    const rows = exchangeRows(list, details);
    expect(rows.every((r) => r.invoiceNumber !== r.number)).toBe(true);
  });
});

describe("settlement", () => {
  it("collected when the new item costs more, refunded when less, even when equal", () => {
    expect(settlementOf({ newValue: 40, returnedValue: 25 })).toEqual({ difference: 15, kind: "collected", amount: 15 });
    expect(settlementOf({ newValue: 60, returnedValue: 100 })).toEqual({ difference: -40, kind: "refunded", amount: 40 });
    expect(settlementOf({ newValue: 25, returnedValue: 25 }).kind).toBe("even");
  });
  it("does not drift on cents", () => expect(settlementOf({ newValue: 0.3, returnedValue: 0.1 }).difference).toBe(0.2));
});

describe("filter and summary", () => {
  const rows = exchangeRows(list, details);
  it("searches the exchange, return, invoice numbers and the items", () => {
    expect(filterExchanges(rows, { term: "pos-ret-9" }).map((r) => r.number)).toEqual(["POS-4"]);
    expect(filterExchanges(rows, { term: "بنطلون" }).map((r) => r.number)).toEqual(["POS-2"]);
  });
  it("filters by settlement and by date", () => {
    expect(filterExchanges(rows, { settlement: "refunded" }).map((r) => r.number)).toEqual(["POS-4"]);
    expect(filterExchanges(rows, { from: "2026-10-20" }).map((r) => r.number)).toEqual(["POS-2"]);
  });
  it("totals collected, refunded and the net exactly", () => {
    expect(summarizeExchanges(rows)).toEqual({ count: 2, newValue: 100, collected: 15, refunded: 40, net: -25, even: 0 });
  });
});
