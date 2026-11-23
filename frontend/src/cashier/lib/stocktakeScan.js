/**
 * Counting by scanner: the code read at the shelf -> the line it belongs to and its new count.
 *
 * A stocktake of a clothing shop is done with a handheld scanner, one piece at a time. The sheet
 * only holds the variants of THIS count, so a code is resolved against the sheet and nowhere else -
 * an item that is not in the count must not be counted into it.
 *
 * An exact barcode, then an exact SKU, always wins over a partial match, so a short code that is a
 * piece of a longer one never picks the wrong garment. A partial match is allowed only when it lands
 * on exactly one line: "أحمر" may find a shirt, but two matches is a question, not a count.
 *
 * Scanning ADDS one to what is already counted on that line. A line nobody has counted yet starts
 * from zero, which is different from "not counted": the count becomes 1, not null.
 */
import { foldCode, foldedIncludes } from "./searchText";

export const MAX_COUNT = 1_000_000;

const exactIn = (rows, field, folded) => rows.filter((r) => foldCode(r[field] ?? "") === folded);

/**
 * `known` is optional: the shop's stock rows. It is only used to tell "not in this count" apart from
 * "no such item", because the cashier needs a different sentence for each.
 * Returns { kind: "empty" | "hit" | "ambiguous" | "outside" | "none", ... }.
 */
export function scanToCount(rows, code, { known = [] } = {}) {
  const clean = String(code ?? "").trim();
  if (!clean) return { kind: "empty" };
  const folded = foldCode(clean);
  if (!folded) return { kind: "empty" };
  const all = rows ?? [];

  let hits = exactIn(all, "barcode", folded);
  if (hits.length === 0) hits = exactIn(all, "sku", folded);
  if (hits.length === 0) {
    hits = all.filter((r) => [r.productName, r.sku, r.barcode].some((field) => foldedIncludes(field ?? "", clean)));
  }
  if (hits.length > 1) return { kind: "ambiguous", count: hits.length };
  if (hits.length === 1) {
    const row = hits[0];
    const was = Number.isFinite(Number(row.actual)) && row.actual !== null ? Number(row.actual) : 0;
    return { kind: "hit", row, wasCounted: row.actual !== null, qty: Math.min(MAX_COUNT, was + 1) };
  }

  // Nothing in the sheet: is it an item the shop has, or a code that belongs to no item at all?
  const elsewhere = (known ?? []).some((k) =>
    [k.barcode, k.sku].some((field) => foldCode(field ?? "") === folded) ||
    [k.productName, k.sku, k.barcode].some((field) => foldedIncludes(field ?? "", clean)),
  );
  return { kind: elsewhere ? "outside" : "none" };
}

/** The sentence for a scan that did not count anything, or null when it did. */
export function scanRefusal(kind, code) {
  const text = String(code ?? "").trim();
  if (kind === "ambiguous") return `أكثر من صنف يطابق «${text}» — امسح الباركود بالكامل`;
  if (kind === "outside") return `«${text}» صنف موجود بالمخزن لكنه مش داخل في هذا الجرد`;
  if (kind === "none") return `لا يوجد صنف في هذا الجرد بـ «${text}»`;
  return null;
}
