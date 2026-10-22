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

describe("receipt discounts: line discount vs invoice discount (report example)", () => {
  // A: 100 at 50% off (paid 50). B: 100. Invoice total 150, discount_total 50 is the LINE discount only.
  const mk = (discountTotal, grand) => ({
    receipt: { id: "r1", number: "POS-1", kind: "sale", issued_at: "2026-10-22T10:00:00Z", tendered_amount: null, change_amount: null },
    order: { id: "o1", number: "S-1", grand_total: grand, discount_total: discountTotal, fully_returned: false },
    lines: [
      { variant_id: "A", title: "A", sku: "A", quantity: 1, unit_price: "100.00", discount_pct: "50.00", total: "50.00", returned_qty: 0 },
      { variant_id: "B", title: "B", sku: "B", quantity: 1, unit_price: "100.00", discount_pct: "0.00", total: "100.00", returned_qty: 0 },
    ],
    tenders: [],
  });
  it("sub-total is the gross before any discount (200), not the post-discount lines (150)", () => {
    expect(receiptFromApi(mk("50.00", "150.00")).subTotal).toBe(200);
  });
  it("the item discount (50) is reported as a line discount", () => {
    expect(receiptFromApi(mk("50.00", "150.00")).lineDiscount).toBe(50);
  });
  it("no invoice-level discount is shown when the whole discount came from the item", () => {
    expect(receiptFromApi(mk("50.00", "150.00")).invoiceDiscount).toBe(0);
  });
  it("an extra invoice discount on top is shown separately (65 total = 50 item + 15 invoice)", () => {
    const r = receiptFromApi(mk("65.00", "135.00"));
    expect(r).toMatchObject({ subTotal: 200, lineDiscount: 50, invoiceDiscount: 15, total: 135 });
  });
  it("sub-total - line discount - invoice discount = total, always", () => {
    const r = receiptFromApi(mk("65.00", "135.00"));
    expect(+(r.subTotal - r.lineDiscount - r.invoiceDiscount).toFixed(2)).toBe(r.total);
  });
  it("each printed line shows its own discount amount", () => {
    const [a, b] = receiptFromApi(mk("50.00", "150.00")).items;
    expect([a.discount, b.discount]).toEqual([50, 0]);
  });
  it("an old receipt without discount_pct on its lines still prints (reads as no line discount)", () => {
    const old = mk("20.00", "180.00");
    old.lines = old.lines.map(({ discount_pct, ...rest }) => ({ ...rest, total: rest.unit_price }));
    expect(receiptFromApi(old)).toMatchObject({ subTotal: 200, lineDiscount: 0, invoiceDiscount: 20 });
  });
});

describe("a sale recorded without any payment", () => {
  const free = receiptFromApi({ ...api, receipt: { ...api.receipt, tendered_amount: null, change_amount: "0.00" }, tenders: [] }, ctx);

  it("says so: there is nothing paid to print, and the total is still the invoice total", () => {
    expect(free.hasPayment).toBe(false);
    expect(free.payments).toEqual([]);
    expect(free.total).toBe(42.5);
  });
  it("an old sale that carries tenders still prints its payment", () => {
    expect(receiptFromApi(api, ctx).hasPayment).toBe(true);
  });
});
