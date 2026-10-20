/**
 * One sale as the details page shows it, built only from the backend's receipts.
 * The sale receipt gives lines/tenders/totals; return receipts of the SAME order (same order_id,
 * kind "return") give the returns. Not stored by the backend, so never shown: branch, customer
 * phone, return reason, who handled it.
 */
import { receiptFromApi } from "./receiptAdapter";

const money = (v) => (v === null || v === undefined ? 0 : Math.round(Number(v) * 100) / 100);

export function returnsOf(saleOrderId, listItems, details) {
  return listItems
    .filter((r) => r.kind === "return" && r.order_id === saleOrderId)
    .map((r) => {
      const d = details[r.id];
      const lines = d?.lines ?? [];
      return {
        id: r.id,
        number: r.number,
        date: r.issued_at,
        amount: money(lines.reduce((s, l) => s + Number(l.total ?? 0), 0)),
        items: lines.map((l) => ({ name: l.title ?? l.sku ?? "—", sku: l.sku ?? "", qty: l.quantity })),
      };
    })
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

export function invoiceFromApi(saleDetail, { returns = [], cashier = "" } = {}) {
  const r = receiptFromApi(saleDetail, { cashier });
  const returned = money(returns.reduce((s, x) => s + x.amount, 0));
  return {
    ...r,
    returns,
    returnedAmount: returned,
    netTotal: money(r.total - returned),
    remaining: money(r.total - (r.paid - r.change)),
  };
}
