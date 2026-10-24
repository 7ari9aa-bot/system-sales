/**
 * One-transaction exchange: lines coming back + replacement lines. The cashier layer never moves
 * money: the backend records the returned goods and the replacement sale (priced off the CURRENT
 * price with NO discount) and the value difference is only shown, never charged or refunded.
 */
import { toMinor } from "./money";
import { estimateRefundMinor } from "./returnPlan";

/** difference = replacement total - estimated return value (cents). Replacement total is the backend quote. */
export function differenceMinor(saleDetail, returnLines, newTotal) {
  return toMinor(newTotal ?? "0") - estimateRefundMinor(saleDetail, returnLines);
}

export function settlementKind(diffMinor) {
  return diffMinor > 0 ? "pay" : diffMinor < 0 ? "refund" : "even";
}

export function exchangeRequest(saleDetail, returnLines, newLines, { restock = true } = {}) {
  const back = returnLines.filter((l) => l.returnQty > 0);
  if (!back.length) throw new Error("اختر صنفًا واحدًا على الأقل لإرجاعه");
  if (!newLines.length) throw new Error("اختر صنفًا بديلًا واحدًا على الأقل");
  return {
    orderId: saleDetail.order.id,
    returnLines: back.map((l) => ({ variant_id: l.variantId, quantity: l.returnQty })),
    newLines: newLines.map((l) => ({ variant_id: l.variantId, quantity: l.qty })),
    restock: Boolean(restock),
  };
}

/** Backend refusals in plain Arabic; anything unknown is passed through, never hidden. */
export function exchangeErrorMessage(err) {
  const m = String(err?.message ?? err ?? "");
  if (/exchanges ride the open drawer|session is closed/i.test(m)) return "الوردية مغلقة. افتح الوردية أولًا لتسجيل الاستبدال.";
  if (/insufficient|not enough stock|out of stock/i.test(m)) return "الكمية المطلوبة من الصنف البديل غير متوفرة في المخزون.";
  return m ? m : "تعذّر تنفيذ الاستبدال";
}

export { sendReturn as sendExchange } from "./returnPlan";
