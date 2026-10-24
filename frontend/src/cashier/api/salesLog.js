/**
 * Sales log rows from the shift's receipts. The list endpoint has no total/pieces/payment, so each
 * row is completed from GET /pos/receipts/{id}. What the backend does NOT return (cashier name,
 * customer) is never invented: the row simply has no such field.
 */
import { receiptFromApi } from "./receiptAdapter";

export const dayOf = (iso) => String(iso).slice(0, 10);

/** Only sales are listed; refund/return receipts belong to the returns screens. */
export function saleReceipts(list) {
  return list.filter((r) => r.kind === "sale");
}

/** `extra.cashier` is the name of whoever ran the shift, when known. Unknown stays empty. */
export function rowFromDetail(detail, extra = {}) {
  const r = receiptFromApi(detail, extra);
  return {
    id: r.id,
    number: r.number,
    date: r.date,
    pieces: r.pieces,
    total: r.total,
    payment: r.payments.length > 1 ? "mixed" : (r.payments[0]?.method ?? null), // a new sale carries no payment: never invent "cash"
    paymentLabel: r.paymentLabel,
    status: r.status,
    items: r.items,
    receipt: r,
  };
}

export function filterRows(rows, { from, to, term, status }) {
  const t = (term ?? "").trim().toLowerCase();
  return rows.filter((row) => {
    const day = dayOf(row.date);
    if (from && day < from) return false;
    if (to && day > to) return false;
    if (status && row.status !== status) return false;
    if (!t) return true;
    return row.number.toLowerCase().includes(t) || row.items.some((i) => String(i.code ?? "").toLowerCase().includes(t) || String(i.name ?? "").toLowerCase().includes(t));
  });
}

export function totalsOf(rows) {
  return rows.reduce((a, r) => ({ total: +(a.total + r.total).toFixed(2), pieces: a.pieces + r.pieces }), { total: 0, pieces: 0 });
}
