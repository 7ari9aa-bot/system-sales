/**
 * Returns log. The receipts LIST gives number/date/order_id/session_id for a return receipt, but its
 * refunded_total / returned_units are computed on the SALE receipt (0/null on the return itself), so
 * quantity and amount come from the return receipt's own lines (GET /pos/receipts/{id}).
 * The original invoice number comes from the "sale" receipt that has the same order_id. Not stored by the backend, so never shown: customer,
 * reason, who handled it, refund method (money always goes back through the original tender).
 */
import { toMinor, fromMinor } from "./money";

export function returnRows(receipts, details = {}) {
  const saleNumber = new Map(receipts.filter((r) => r.kind === "sale").map((r) => [r.order_id, r.number]));
  return receipts
    .filter((r) => r.kind === "return")
    .map((r) => ({
      id: r.id,
      number: r.number,
      date: r.issued_at,
      invoiceId: r.order_id,
      invoiceNumber: saleNumber.get(r.order_id) ?? "—",
      sessionId: r.session_id,
      qty: (details[r.id]?.lines ?? []).reduce((n, l) => n + Number(l.quantity ?? 0), 0),
      amount: Number(fromMinor((details[r.id]?.lines ?? []).reduce((c, l) => c + toMinor(l.total ?? "0"), 0))),
    }))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

export function filterReturns(rows, { term = "", from = "", to = "" } = {}) {
  const t = term.trim().toLowerCase();
  return rows.filter((r) => {
    const day = String(r.date).slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    return !t || r.number.toLowerCase().includes(t) || r.invoiceNumber.toLowerCase().includes(t);
  });
}

export function summarizeReturns(rows) {
  const cents = rows.reduce((s, r) => s + toMinor(r.amount), 0);
  return { count: rows.length, qty: rows.reduce((s, r) => s + r.qty, 0), amount: Number(fromMinor(cents)) };
}
