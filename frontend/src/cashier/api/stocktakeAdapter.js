/**
 * The stocktake sheet: backend count lines + the stock rows (names, colour, size) -> table rows,
 * and the edited table -> the counts to save.
 *
 * Rules that live HERE because the screen would otherwise get them wrong:
 *  - "not counted" is `null`, NOT 0. A shelf nobody counted must never turn into "0 in stock".
 *  - The difference is `counted - expected`, where `expected` is the book quantity when counting
 *    STARTED (the server's snapshot). It is NOT compared with the live balance, so a sale made
 *    while counting does not show up as a missing item.
 *  - `drift` is how far the live balance moved since the snapshot (sales/receipts during the count).
 *    It is shown, never folded into the difference.
 */

export const MAX_COUNT = 1_000_000;

/** A typed value -> a count (whole number 0..MAX) or null for an empty box. Throws on junk. */
export function parseCount(text) {
  const s = String(text ?? "").trim();
  if (s === "") return null;
  if (!/^\d+$/.test(s)) throw new RangeError("الكمية يجب أن تكون عددًا صحيحًا موجبًا");
  const n = Number(s);
  if (n > MAX_COUNT) throw new RangeError(`الكمية لا تزيد عن ${MAX_COUNT}`);
  return n;
}

/** Join the server's lines with the stock rows (which carry the product name, colour and size). */
export function sheetFromApi(detail, stockRows) {
  const byId = new Map((stockRows ?? []).map((r) => [r.id, r]));
  const rows = (detail?.lines ?? []).map((line) => {
    const meta = byId.get(line.variant_id);
    const counted = line.counted_qty ?? null;
    return {
      id: line.variant_id,
      productName: meta?.productName ?? "صنف غير معروف",
      sku: meta?.sku ?? "",
      color: meta?.color ?? "",
      size: meta?.size ?? "",
      stock: line.expected_qty, // the book quantity when counting started
      actual: counted, // null = not counted yet
      current: line.current_qty, // the live balance now
      drift: line.current_qty - line.expected_qty,
      applied: line.applied_delta ?? null,
    };
  });
  return {
    id: detail?.id ?? null,
    status: detail?.status ?? "OPEN",
    note: detail?.note ?? "",
    closedAt: detail?.closed_at ?? null,
    rows,
  };
}

export const diffOf = (row) => (row.actual === null ? null : row.actual - row.stock);

/** Totals for the four cards. Only COUNTED lines contribute to the difference. */
export function sheetTotals(rows) {
  let counted = 0;
  let withDiff = 0;
  let net = 0;
  for (const r of rows) {
    const d = diffOf(r);
    if (d === null) continue;
    counted += 1;
    if (d !== 0) {
      withDiff += 1;
      net += d;
    }
  }
  return { total: rows.length, counted, notCounted: rows.length - counted, withDiff, net };
}

/** The lines whose count differs from what the server already holds (so we save only the changes). */
export function changedCounts(rows, saved) {
  const was = new Map((saved?.rows ?? []).map((r) => [r.id, r.actual]));
  return rows
    .filter((r) => (was.get(r.id) ?? null) !== r.actual)
    .map((r) => ({ variant_id: r.id, counted_qty: r.actual }));
}

/** Why the server said no, in words the person at the counter can act on. */
export function stocktakeErrorMessage(error, action = "save") {
  const status = error?.status;
  if (status === 403) {
    return action === "approve" ? "اعتماد الجرد من صلاحية المدير أو المالك فقط" : "ليست لديك صلاحية على الجرد";
  }
  if (status === 404) return "هذا الجرد لم يعد موجودًا";
  if (status === 409) {
    return action === "open" ? "يوجد جرد مفتوح بالفعل" : "هذا الجرد أُغلق من شاشة أخرى. حدّث الصفحة";
  }
  if (status === 400 || status === 422) {
    return action === "approve" ? "لا توجد كميات معدودة لاعتمادها" : "الكميات المدخلة غير صالحة";
  }
  return "تعذّر إتمام العملية، حاول مرة أخرى";
}
