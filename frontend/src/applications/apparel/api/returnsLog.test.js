import { describe, expect, it } from "vitest";
import { filterReturns, returnRows, summarizeReturns } from "./returnsLog";

const list = [
  { id: "s1", kind: "sale", number: "POS-1", order_id: "o1", session_id: "A", issued_at: "2026-10-20T09:00:00Z" },
  { id: "r1", kind: "return", number: "POS-RET-1", order_id: "o1", session_id: "A", issued_at: "2026-10-20T10:00:00Z" },
  { id: "r2", kind: "return", number: "POS-RET-2", order_id: "o1", session_id: "A", issued_at: "2026-10-20T11:00:00Z" },
  { id: "s2", kind: "sale", number: "POS-2", order_id: "o2", session_id: "B", issued_at: "2026-10-19T09:00:00Z" },
  { id: "r3", kind: "return", number: "POS-RET-3", order_id: "o2", session_id: "B", issued_at: "2026-10-19T12:00:00Z" },
];

const details = {
  r1: { lines: [{ quantity: 1, total: "113.33" }] },
  r2: { lines: [{ quantity: 1, total: "0.05" }, { quantity: 1, total: "0.05" }] },
  r3: { lines: [{ quantity: 1, total: "50.00" }] },
};

describe("returnRows", () => {
  it("lists only return receipts, newest first", () => expect(returnRows(list, details).map((r) => r.number)).toEqual(["POS-RET-2", "POS-RET-1", "POS-RET-3"]));
  it("links each to the ORIGINAL invoice number of the same order", () => {
    const r = returnRows(list, details);
    expect(r.find((x) => x.number === "POS-RET-3").invoiceNumber).toBe("POS-2");
    expect(r.find((x) => x.number === "POS-RET-1").invoiceNumber).toBe("POS-1");
  });
  it("unknown original sale shows a dash, not a guess", () => expect(returnRows([list[1]])[0].invoiceNumber).toBe("—"));
  it("amount and qty come from the return receipt's own lines, not the list fields", () => {
    const withMisleadingListFields = list.map((r) => (r.kind === "return" ? { ...r, refunded_total: null, returned_units: 0 } : r));
    const r = returnRows(withMisleadingListFields, details).find((x) => x.id === "r2");
    expect([r.qty, r.amount]).toEqual([2, 0.1]);
  });
  it("missing numbers become 0, not NaN", () => {
    const r = returnRows([{ id: "x", kind: "return", number: "R", order_id: "o", issued_at: "2026-10-20T00:00:00Z" }])[0];
    expect([r.qty, r.amount]).toEqual([0, 0]);
  });
});

describe("filterReturns", () => {
  const rows = returnRows(list, details);
  it("by return number", () => expect(filterReturns(rows, { term: "ret-3" }).map((r) => r.id)).toEqual(["r3"]));
  it("by original invoice number", () => expect(filterReturns(rows, { term: "pos-1" }).map((r) => r.id)).toEqual(["r2", "r1"]));
  it("by day range", () => expect(filterReturns(rows, { from: "2026-10-20" }).length).toBe(2));
  it("empty filter keeps all", () => expect(filterReturns(rows, {}).length).toBe(3));
});

describe("summarizeReturns", () => {
  it("sums exactly in cents (113.33 + 0.10 + 50.00)", () => expect(summarizeReturns(returnRows(list, details))).toEqual({ count: 3, qty: 4, amount: 163.43 }));
  it("empty is zeros", () => expect(summarizeReturns([])).toEqual({ count: 0, qty: 0, amount: 0 }));
});
