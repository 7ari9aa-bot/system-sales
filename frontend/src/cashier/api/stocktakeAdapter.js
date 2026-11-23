/**
 * The stocktake sheet: backend count lines + the stock rows (names, colour, size) -> table rows,
 * and the edited table -> the counts to save.
 *
 * Rules that live HERE because the screen would otherwise get them wrong:
 *  - "not counted" is `null`, NOT 0. A shelf nobody counted must never turn into "0 in stock".
 *  - The difference is `counted - book`, where `book` is the quantity the SERVER will compare
 *    against: ``counted_book_qty``, the figure stored at the moment that piece was counted. It is
 *    NOT the live balance, so a sale made while counting does not show up as a missing item; and
 *    it is not the count's start snapshot either, because stock that moved between the start and
 *    the count would then be shown as a difference the server never applies. A line counted before
 *    that column existed falls back to the start snapshot, exactly like the server does.
 *  - `drift` is how far the live balance moved since the piece was counted. Shown, never folded
 *    into the difference.
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

/**
 * What a finished line should save, decided from the box and what the server already holds.
 *
 * The server stamps ``counted_at`` when the count arrives, so a count that waits for the sheet's
 * Save button is recorded as taken at the END of the count. Each line is committed when the piece
 * is done, and this decides whether there is anything to send: junk is left to the red cell, a
 * value the server already holds needs no request, and a cleared box is a real un-count.
 */
export function commitDecision(raw, actual) {
  let qty;
  try {
    qty = parseCount(raw);
  } catch {
    return { send: false, reason: "invalid" };
  }
  if (qty === (actual ?? null)) return { send: false, reason: "unchanged" };
  return { send: true, qty };
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
      // The scanner at the shelf reads a barcode, not a SKU: the sheet needs the code to match it.
      barcode: meta?.barcode ?? "",
      color: meta?.color ?? "",
      size: meta?.size ?? "",
      // The book the server reconciles against for THIS line: at count time when it was counted,
      // else the start snapshot (the same fallback the server applies).
      stock: line.counted_book_qty ?? line.expected_qty,
      startBook: line.expected_qty, // the count's opening snapshot, kept only to explain drift
      countedAt: line.counted_at ?? null,
      actual: counted, // null = not counted yet
      current: line.current_qty, // the live balance now
      drift: line.current_qty - (line.counted_book_qty ?? line.expected_qty),
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

/**
 * The one save request built from what the cashier typed and what the scanner queued.
 *
 * Scanning saves on its own, and that save refetches the sheet, which drops the typed counts - so
 * a save started by a scan must carry the hand-typed rows too, or an hour of counting in the
 * second half of the sheet disappears because someone scanned a tag. The scanned line wins for its
 * own variant: it is the newer number.
 */
export function countsToSave(pending = [], queued = {}) {
  const byId = new Map((pending ?? []).map((c) => [String(c.variant_id), c]));
  for (const [variantId, countedQty] of Object.entries(queued ?? {})) {
    byId.set(String(variantId), { variant_id: variantId, counted_qty: countedQty });
  }
  return [...byId.values()];
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
