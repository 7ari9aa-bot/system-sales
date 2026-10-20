/**
 * GET /pos/receipts/{id} -> the receipt the dialog prints. The record is built from the server's
 * copy, not from screen state, so a reprint after a reload shows exactly what was charged.
 * "paid" is what the customer handed over: cash tendered plus non-cash tenders. The server's
 * change is passed through, and paid - change always equals the order total.
 */
import { parseMoney } from "./money";

const num = (wire) => (wire === null || wire === undefined ? 0 : parseMoney(wire).minor / 100);
const LABELS = { cash: "نقدي", card: "بطاقة", wallet: "محفظة إلكترونية", bank_transfer: "تحويل بنكي" };

export function receiptFromApi(data, { cashier = "", customerName = "", names = {} } = {}) {
  const { receipt, order, lines = [], tenders = [] } = data;
  const payments = tenders.map((t) => ({ method: t.method, label: LABELS[t.method] ?? t.method, amount: num(t.amount) }));
  const nonCash = payments.filter((p) => p.method !== "cash").reduce((s, p) => s + p.amount, 0);
  const cashPaid = payments.filter((p) => p.method === "cash").reduce((s, p) => s + p.amount, 0);
  const change = num(receipt.change_amount);
  const tenderedCash = receipt.tendered_amount === null || receipt.tendered_amount === undefined ? cashPaid : num(receipt.tendered_amount);
  const items = lines.map((l) => {
    const price = num(l.unit_price);
    return {
      lineId: l.variant_id,
      variantId: l.variant_id,
      name: names[l.variant_id] ?? l.title,
      code: l.sku,
      size: l.title,
      color: "",
      qty: l.quantity,
      price,
      discount: 0,
      total: num(l.total),
      returnedQty: l.returned_qty ?? 0,
    };
  });
  const subTotal = items.reduce((s, i) => s + i.total, 0);
  return {
    id: receipt.id,
    orderId: order.id,
    number: receipt.number,
    orderNumber: order.number,
    date: receipt.issued_at,
    cashier,
    customerName: customerName.trim() || "عميل نقدي",
    customerPhone: "—",
    items,
    pieces: items.reduce((s, i) => s + i.qty, 0),
    subTotal: +subTotal.toFixed(2),
    lineDiscount: 0,
    invoiceDiscount: num(order.discount_total),
    discount: num(order.discount_total),
    total: num(order.grand_total),
    paid: +(tenderedCash + nonCash).toFixed(2),
    change,
    payments,
    paymentLabel: payments.map((p) => p.label).join(" + "),
    note: "",
    status: order.fully_returned ? "returned" : "paid",
  };
}
