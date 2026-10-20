/**
 * Pure checkout rules for the POS screen (no React, no network), so the money logic is testable.
 *
 * The backend is the authority on prices and totals (/quote). This file only (a) keeps quantities
 * within stock, because /quote does not check it, and (b) turns what the cashier typed into a
 * /sell payload whose tenders equal the order total to the cent. Cash over-tender is expressed
 * the way the backend expects: tenders sum to the total, `tenderedCash` carries what was handed
 * over, and the server computes the change.
 */
import { fromMinor, toMinor } from "./money";

export function clampQty(value, max) {
  if (max <= 0) return 0;
  const n = Math.floor(Number(value));
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, max);
}

export function cartItems(cart) {
  return cart.map((l) => ({ variant_id: l.variantId, quantity: l.qty }));
}

function minorOf(value) {
  try {
    return toMinor(value ?? 0);
  } catch {
    return Number.NaN;
  }
}

/**
 * @param {{ total: string|number, tenders: {method:string, amount:string|number}[] }} input
 * @returns {{ ok: boolean, reason?: string, remaining: string, change: string, tenderedCash?: string, tenders: {method:string, amount:string}[] }}
 */
export function settle({ total, tenders }) {
  const totalMinor = minorOf(total);
  const fail = (reason, remaining = totalMinor) => ({ ok: false, reason, remaining: fromMinor(Math.max(0, remaining)), change: "0.00", tenders: [] });
  if (!Number.isFinite(totalMinor) || totalMinor <= 0) return fail("لا يوجد إجمالي للدفع");

  const rows = [];
  for (const t of tenders ?? []) {
    const m = minorOf(t.amount);
    if (!Number.isFinite(m)) return fail("مبلغ غير صالح");
    if (m < 0) return fail("لا يمكن إدخال مبلغ سالب");
    if (m > 0) rows.push({ method: t.method, minor: m });
  }
  const paid = rows.reduce((s, r) => s + r.minor, 0);
  if (paid < totalMinor) return fail("المبلغ المدفوع أقل من الإجمالي", totalMinor - paid);

  const excess = paid - totalMinor;
  const cashTotal = rows.filter((r) => r.method === "cash").reduce((s, r) => s + r.minor, 0);
  const nonCash = paid - cashTotal;
  // Change can only come out of cash, and the non-cash tenders must NOT already cover the
  // total on their own (otherwise the cash handed over was never owed: card 50 + cash 10 on a 50 sale).
  if (excess > cashTotal || nonCash > totalMinor || (excess > 0 && nonCash >= totalMinor)) {
    return fail("الزيادة عن الإجمالي مسموحة في النقدية فقط (لا باقي على بطاقة أو محفظة)", 0);
  }

  // Trim the excess off the cash rows (last cash row first) so the tenders sum to the total exactly.
  let toTrim = excess;
  const trimmed = rows.map((r) => ({ ...r }));
  for (let i = trimmed.length - 1; i >= 0 && toTrim > 0; i -= 1) {
    if (trimmed[i].method !== "cash") continue;
    const cut = Math.min(trimmed[i].minor, toTrim);
    trimmed[i].minor -= cut;
    toTrim -= cut;
  }
  return {
    ok: true,
    remaining: "0.00",
    change: fromMinor(excess),
    tenderedCash: excess > 0 || cashTotal > 0 ? fromMinor(cashTotal) : undefined,
    tenders: trimmed.filter((r) => r.minor > 0).map((r) => ({ method: r.method, amount: fromMinor(r.minor) })),
  };
}

export function buildSellPayload({ cart, total, discountTotal, customerId, tenders }) {
  if (!cart?.length) throw new RangeError("checkout: the cart is empty");
  const s = settle({ total, tenders });
  if (!s.ok) throw new RangeError(`checkout: ${s.reason}`);
  const hasDiscount = discountTotal !== undefined && discountTotal !== null && minorOf(discountTotal) > 0;
  return {
    items: cartItems(cart),
    tenders: s.tenders,
    tenderedCash: s.tenderedCash,
    discountTotal: hasDiscount ? fromMinor(minorOf(discountTotal)) : undefined,
    customerId: customerId || undefined,
  };
}
