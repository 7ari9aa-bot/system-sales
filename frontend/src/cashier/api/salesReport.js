/**
 * Sales report. The backend counts each SHOP day straight from the receipts (same rules as the shift
 * report), so a day here always equals the sum of its shifts. Strings from the API are money: they go
 * through toMinor/fromMinor, never float arithmetic.
 */
import { fromMinor, toMinor } from "./money";

const money = (v) => Number(fromMinor(toMinor(v ?? "0")));

export function salesRows(apiRows = []) {
  return apiRows
    .map((r) => ({
      id: r.date,
      date: r.date,
      invoices: Number(r.invoices ?? 0),
      pieces: Number(r.pieces ?? 0),
      gross: money(r.gross),
      discount: money(r.discount),
      returns: money(r.returns),
      returnsCount: Number(r.returns_count ?? 0),
      net: money(r.net),
    }))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

export function summarizeSales(rows) {
  const sum = (k) => rows.reduce((c, r) => c + toMinor(r[k]), 0);
  return {
    invoices: rows.reduce((n, r) => n + r.invoices, 0),
    pieces: rows.reduce((n, r) => n + r.pieces, 0),
    gross: Number(fromMinor(sum("gross"))),
    discount: Number(fromMinor(sum("discount"))),
    returns: Number(fromMinor(sum("returns"))),
    net: Number(fromMinor(sum("net"))),
  };
}
