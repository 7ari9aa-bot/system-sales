/**
 * Pure cart rules for the POS screen (no React, no network). The backend is the authority on
 * prices and totals (/quote). This file only keeps quantities within stock (because /quote does
 * not check it) and turns the cart into the line items a sale is recorded with. There is no
 * payment here: the cashier layer records the sale, it never takes money.
 */

export function clampQty(value, max) {
  if (max <= 0) return 0;
  const n = Math.floor(Number(value));
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, max);
}

/**
 * Undo a deleted line: the SAME line goes back at its old position with its quantity and discount.
 * Stock is the live figure (it may have dropped since), so the quantity is clamped and the
 * money-discount recomputed for the new quantity; never more than is on the shelf.
 * Returns { ok:false, reason } or { ok:true, lines, clamped }.
 */
export function restoreRemovedLine(lines, line, index, liveStock) {
  const stock = Number(liveStock ?? line.stock);
  if (!Number.isFinite(stock) || stock <= 0) return { ok: false, reason: "نافد من المخزون" };
  if (lines.some((l) => l.variantId === line.variantId)) return { ok: true, lines, clamped: false }; // added again meanwhile: keep that one
  const qty = clampQty(line.qty, stock);
  const clamped = qty < line.qty;
  const discount = clamped ? +((line.price * qty * (line.discountPct || 0)) / 100).toFixed(2) : line.discount;
  const next = [...lines];
  next.splice(Math.min(Math.max(index, 0), next.length), 0, { ...line, qty, stock, discount });
  return { ok: true, lines: next, clamped };
}

/**
 * The cart as the server prices it. A line's own percentage discount travels WITH the line
 * (`discount_pct`): the server stores it on the sale line and a later return refunds what that
 * line actually paid. Folding it into one invoice-wide amount would make the server spread the
 * discount over every line, so returning the discounted item alone would refund the wrong sum.
 */
export function cartItems(cart) {
  return cart.map((l) => {
    const pct = Number(l.discountPct) || 0;
    const item = { variant_id: l.variantId, quantity: l.qty };
    return pct > 0 ? { ...item, discount_pct: pct.toFixed(2) } : item;
  });
}
