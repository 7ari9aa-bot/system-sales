/**
 * Exchanges log. An exchange is TWO receipts issued together: a return receipt for what came back and a
 * NEW sale receipt for what went out. The backend stores the pairing on the new sale receipt
 * (`exchange_return_receipt_id` -> the return receipt), so an exchange is exactly a sale receipt that has it.
 * Exchanges made before that link existed show up as a return plus a sale: nothing is guessed.
 *
 * Values come from the receipts themselves: what came back = the return receipt's own lines, what went out =
 * the new order's grand total. Not stored by the backend, so never shown: customer, employee, a "review"
 * status. (The settlement is derived: new minus returned.)
 */
import { fromMinor, toMinor } from "./money";

const cents = (lines, field) => (lines ?? []).reduce((c, l) => c + toMinor(l?.[field] ?? "0"), 0);
const units = (lines) => (lines ?? []).reduce((n, l) => n + Number(l?.quantity ?? 0), 0);
const label = (l) => l?.title ?? l?.sku ?? "—";

/** Receipts list -> pairs (new sale receipt, its return receipt). Details are keyed by receipt id. */
export function exchangeRows(receipts, details = {}) {
  const byId = new Map(receipts.map((r) => [r.id, r]));
  const saleByOrder = new Map(receipts.filter((r) => r.kind === "sale" && !r.exchange_return_receipt_id).map((r) => [r.order_id, r]));
  return receipts
    .filter((r) => r.kind === "sale" && r.exchange_return_receipt_id)
    .map((n) => {
      const ret = byId.get(n.exchange_return_receipt_id);
      const returnedLines = details[n.exchange_return_receipt_id]?.lines ?? [];
      const newLines = details[n.id]?.lines ?? [];
      const original = ret ? saleByOrder.get(ret.order_id) : null;
      return {
        id: n.id,
        number: n.number,
        returnReceiptNumber: ret?.number ?? "—",
        date: n.issued_at,
        sessionId: n.session_id,
        invoiceId: original?.id ?? ret?.order_id ?? null,
        invoiceNumber: original?.number ?? "—",
        returnedItem: returnedLines.map(label).join("، ") || "—",
        newItem: newLines.map(label).join("، ") || "—",
        returnedQty: units(returnedLines),
        newQty: units(newLines),
        returnedValue: Number(fromMinor(cents(returnedLines, "total"))),
        newValue: Number(fromMinor(toMinor(details[n.id]?.order?.grand_total ?? "0"))),
      };
    })
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

/** new minus returned: positive = the customer pays, negative = the shop refunds. */
export function settlementOf(row) {
  const difference = Number(fromMinor(toMinor(row.newValue) - toMinor(row.returnedValue)));
  return { difference, kind: difference > 0 ? "collected" : difference < 0 ? "refunded" : "even", amount: Math.abs(difference) };
}

export function filterExchanges(rows, { term = "", settlement = "", from = "", to = "" } = {}) {
  const t = term.trim().toLowerCase();
  return rows.filter((r) => {
    const day = String(r.date).slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    if (settlement && settlementOf(r).kind !== settlement) return false;
    return !t || [r.number, r.returnReceiptNumber, r.invoiceNumber, r.newItem, r.returnedItem].some((v) => String(v).toLowerCase().includes(t));
  });
}

export function summarizeExchanges(rows) {
  let collected = 0;
  let refunded = 0;
  let even = 0;
  let newValue = 0;
  for (const r of rows) {
    const d = toMinor(r.newValue) - toMinor(r.returnedValue);
    newValue += toMinor(r.newValue);
    if (d > 0) collected += d;
    else if (d < 0) refunded += -d;
    else even += 1;
  }
  return { count: rows.length, newValue: Number(fromMinor(newValue)), collected: Number(fromMinor(collected)), refunded: Number(fromMinor(refunded)), net: Number(fromMinor(collected - refunded)), even };
}
