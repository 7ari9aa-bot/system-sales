import { describe, expect, it } from "vitest";
import { invoiceFromApi, returnsOf } from "./invoiceDetail";

const sale = {
  receipt: { id: "s1", number: "POS-1", kind: "sale", issued_at: "2026-10-20T09:00:00+00:00", tendered_amount: "300.00", change_amount: "60.00" },
  order: { id: "o1", number: "ORD-1", grand_total: "240.00", discount_total: "0.00", fully_returned: false },
  lines: [{ variant_id: "v1", title: "قميص", sku: "SH-1", quantity: 2, unit_price: "120.00", total: "240.00", returned_qty: 1 }],
  tenders: [{ method: "cash", amount: "240.00", status: "captured" }],
};
const list = [
  { id: "s1", kind: "sale", order_id: "o1", number: "POS-1" },
  { id: "r1", kind: "return", order_id: "o1", number: "POS-RET-1", issued_at: "2026-10-20T10:00:00+00:00" },
  { id: "r2", kind: "return", order_id: "OTHER", number: "POS-RET-2", issued_at: "2026-10-20T11:00:00+00:00" },
];
const details = { r1: { lines: [{ title: "قميص", sku: "SH-1", quantity: 1, total: "120.00" }] }, r2: { lines: [{ title: "x", quantity: 1, total: "999.00" }] } };

describe("returnsOf", () => {
  it("only returns of THIS order", () => {
    const r = returnsOf("o1", list, details);
    expect(r.map((x) => x.number)).toEqual(["POS-RET-1"]);
    expect(r[0]).toMatchObject({ amount: 120, items: [{ name: "قميص", qty: 1 }] });
  });
  it("a sale receipt is never a return", () => expect(returnsOf("o1", [{ id: "s1", kind: "sale", order_id: "o1" }], {})).toEqual([]));
  it("no returns -> empty", () => expect(returnsOf("o9", list, details)).toEqual([]));
  it("missing detail does not crash and counts as 0", () => expect(returnsOf("o1", list, {})[0].amount).toBe(0));
});

describe("invoiceFromApi", () => {
  it("net total subtracts what was handed back", () => {
    const inv = invoiceFromApi(sale, { returns: returnsOf("o1", list, details) });
    expect(inv).toMatchObject({ total: 240, returnedAmount: 120, netTotal: 120, status: "partial_return" });
  });
  it("fully paid invoice has nothing remaining", () => expect(invoiceFromApi(sale).remaining).toBe(0));
  it("a sale recorded without any payment owes nothing through the POS", () => {
    const inv = invoiceFromApi({ ...sale, tenders: [] });
    expect(inv.hasPayment).toBe(false);
    expect(inv.remaining).toBe(0);
  });
  it("no returns -> net equals total", () => {
    const inv = invoiceFromApi({ ...sale, lines: [{ ...sale.lines[0], returned_qty: 0 }] });
    expect(inv).toMatchObject({ netTotal: 240, returnedAmount: 0, status: "paid" });
  });
  it("does not invent branch or customer phone", () => {
    const inv = invoiceFromApi(sale);
    expect(inv.branch).toBeUndefined();
    expect(inv.customerPhone).toBe("—");
  });
});
