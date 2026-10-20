import { describe, expect, it } from "vitest";
import { receiptFromApi } from "./receiptAdapter";

// A real response from GET /pos/receipts/{id}: cash 32.50 + card 10.00 on a 42.50 order,
// the customer handed over 40.00 cash (so 7.50 change) and 10.00 on the card.
const api = {
  receipt: { id: "r1", number: "POS-20261020-D89DF0", kind: "sale", issued_at: "2026-10-20T09:49:01+00:00", tendered_amount: "40.00", change_amount: "7.50" },
  order: { id: "o1", number: "ORD-1", grand_total: "42.50", discount_total: "7.50", currency: "EGP", fully_returned: false },
  lines: [{ variant_id: "v1", title: "M", sku: "SKU-1", quantity: 2, unit_price: "25.00", total: "50.00", returned_qty: 0 }],
  tenders: [{ method: "cash", amount: "32.50", status: "captured" }, { method: "card", amount: "10.00", status: "captured" }],
};
const ctx = { cashier: "سارة", customerName: "", names: { v1: "قميص قطن" } };

describe("receiptFromApi", () => {
  const r = receiptFromApi(api, ctx);

  it("numbers and totals come from the server record", () => {
    expect(r).toMatchObject({ number: "POS-20261020-D89DF0", orderNumber: "ORD-1", total: 42.5, discount: 7.5, subTotal: 50, pieces: 2, status: "paid", cashier: "سارة" });
  });
  it("paid = what the customer handed over (cash tendered + non-cash); change is the server's", () => {
    expect(r.paid).toBe(50);
    expect(r.change).toBe(7.5);
    expect(+(r.paid - r.change).toFixed(2)).toBe(r.total); // the books balance
  });
  it("a split payment is listed as every method with its amount", () => {
    expect(r.payments).toEqual([{ method: "cash", label: "نقدي", amount: 32.5 }, { method: "card", label: "بطاقة", amount: 10 }]);
    expect(r.paymentLabel).toBe("نقدي + بطاقة");
  });
  it("lines carry name, sku, qty and the server's price/total", () => {
    expect(r.items).toEqual([expect.objectContaining({ name: "قميص قطن", code: "SKU-1", qty: 2, price: 25, total: 50, size: "M" })]);
  });
  it("no customer name falls back to the cash customer", () => expect(r.customerName).toBe("عميل نقدي"));
  it("a line whose product name is unknown still prints (falls back to the variant title)", () => {
    expect(receiptFromApi(api, { ...ctx, names: {} }).items[0].name).toBe("M");
  });
  it("exact payment: paid equals total and change is zero", () => {
    const exact = { ...api, receipt: { ...api.receipt, tendered_amount: "42.50", change_amount: "0.00" }, tenders: [{ method: "cash", amount: "42.50" }] };
    const e = receiptFromApi(exact, ctx);
    expect(e).toMatchObject({ paid: 42.5, change: 0, paymentLabel: "نقدي" });
  });
  it("card-only sale has no cash tendered: paid is the card amount", () => {
    const card = { ...api, receipt: { ...api.receipt, tendered_amount: null, change_amount: null }, tenders: [{ method: "card", amount: "42.50" }] };
    expect(receiptFromApi(card, ctx)).toMatchObject({ paid: 42.5, change: 0 });
  });
  it("a fully returned order is flagged so the screen can say so", () => {
    expect(receiptFromApi({ ...api, order: { ...api.order, fully_returned: true } }, ctx).status).toBe("returned");
  });
});
