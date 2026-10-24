/**
 * One-transaction exchange: lines coming back + replacement lines. The backend decides everything that
 * is money: it prices the replacement off the CURRENT price with NO discount, credits the return across
 * the original tenders, charges only the difference. This file builds the request and tells the screen
 * what the cashier has to do next:  pay (difference > 0), hand back (< 0) or nothing (= 0).
 */
import { fromMinor, toMinor } from "./money";
import { settle } from "./checkout";
import { estimateRefundMinor } from "./returnPlan";

/** difference = replacement total - estimated return value (cents). Replacement total is the backend quote. */
export function differenceMinor(saleDetail, returnLines, newTotal) {
  return toMinor(newTotal ?? "0") - estimateRefundMinor(saleDetail, returnLines);
}

/**
 * The cashier never takes payment. An exchange records the goods and the value; a difference the
 * customer owes is shown on the screen and is never charged, whatever the original sale took.
 * Kept as a function so the screen has one place that answers "ask for money?": always no.
 */
export function needsPayment(_detail, _diffMinor) {
  return false;
}

export function settlementKind(diffMinor) {
  return diffMinor > 0 ? "pay" : diffMinor < 0 ? "refund" : "even";
}

/** Tenders for the difference the customer owes. Not needed (and not sent) when it is <= 0. */
export function exchangePayment(diffMinor, tenders) {
  if (diffMinor <= 0) return { ok: true, tenders: undefined, tenderedCash: undefined };
  const s = settle({ total: fromMinor(diffMinor), tenders });
  return s.ok ? { ok: true, tenders: s.tenders, tenderedCash: s.tenderedCash } : { ok: false, reason: s.reason, remaining: s.remaining };
}

export function exchangeRequest(saleDetail, returnLines, newLines, { restock = true, tenders, tenderedCash } = {}) {
  const back = returnLines.filter((l) => l.returnQty > 0);
  if (!back.length) throw new Error("اختر صنفًا واحدًا على الأقل لإرجاعه");
  if (!newLines.length) throw new Error("اختر صنفًا بديلًا واحدًا على الأقل");
  return {
    orderId: saleDetail.order.id,
    returnLines: back.map((l) => ({ variant_id: l.variantId, quantity: l.returnQty })),
    newLines: newLines.map((l) => ({ variant_id: l.variantId, quantity: l.qty })),
    restock: Boolean(restock),
    tenders,
    tenderedCash,
  };
}

/** Backend refusals in plain Arabic; anything unknown is passed through, never hidden. */
export function exchangeErrorMessage(err) {
  const m = String(err?.message ?? err ?? "");
  if (/exchange difference is|tenders total/i.test(m)) return "مبلغ الدفع لا يطابق فرق الاستبدال. راجع المدفوع.";
  if (/exchanges ride the open drawer|session is closed/i.test(m)) return "الوردية مغلقة. افتح الوردية أولًا لتسجيل الاستبدال.";
  if (/insufficient|not enough stock|out of stock/i.test(m)) return "الكمية المطلوبة من الصنف البديل غير متوفرة في المخزون.";
  return m ? m : "تعذّر تنفيذ الاستبدال";
}

export { sendReturn as sendExchange } from "./returnPlan";
