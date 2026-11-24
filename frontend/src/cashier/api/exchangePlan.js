/**
 * One-transaction exchange: lines coming back + replacement lines + the price difference.
 *
 * The difference is real money. The server refuses a replacement that costs more unless the
 * request carries the tender that covers it, and refunds the difference across the original
 * tenders when the replacement costs less - so this file refuses the same things first, in Arabic,
 * before any request: no line, a method the till does not accept, a missing reference, an amount
 * that does not cover the difference, or a difference nobody settled.
 *
 * A till with `pos.take_payments` off moves no money at all (`record_only`): nothing is collected
 * and nothing is refunded, and the request says so by carrying no payments and no refund.
 */
import { fromMinor, toMinor } from "./money";
import { buildTender } from "./tenderPlan";
import { estimateRefundMinor, wireLine } from "./returnPlan";

/** difference = replacement total - estimated return value (cents). Replacement total is the backend quote. */
export function differenceMinor(saleDetail, returnLines, newTotal) {
  return toMinor(newTotal ?? "0") - estimateRefundMinor(saleDetail, returnLines);
}

export function settlementKind(diffMinor) {
  return diffMinor > 0 ? "pay" : diffMinor < 0 ? "refund" : "even";
}

/** What the cashier must do about the difference, in one line the screen can print. */
export function settlementPrompt(kind, diffMinor, { takePayments = false } = {}) {
  if (kind === "even") return "لا فرق في القيمة: الاستبدال بيمشي من غير تحصيل ولا رد";
  if (!takePayments) return "الكاشير ده مش بيسجّل مدفوعات: الفرق بيتسجّل على الفاتورة بس، ومش بيتحصّل ولا بيترد من هنا";
  return kind === "pay"
    ? `لازم تحصّل ${fromMinor(diffMinor)} من العميل قبل ما تتم الاستبدال`
    : `${fromMinor(-diffMinor)} ترجع للعميل على وسيلة الدفع الأصلية`;
}

/**
 * The request body. `differenceMinor` is the value the screen already showed; the tender lines are
 * only used when the customer owes money and the till records payments.
 */
export function exchangeRequest(
  saleDetail,
  returnLines,
  newLines,
  { restock, reason, rules = null, differenceMinor: diffMinor = null, tenderLines = [], refundMethod = null } = {},
) {
  const back = returnLines.filter((l) => l.returnQty > 0);
  if (!back.length) throw new Error("اختر صنفًا واحدًا على الأقل لإرجاعه");
  if (!newLines.length) throw new Error("اختر صنفًا بديلًا واحدًا على الأقل");
  const body = {
    orderId: saleDetail.order.id,
    returnLines: back.map((l) => wireLine(l, reason)),
    newLines: newLines.map((l) => ({ variant_id: l.variantId, quantity: l.qty })),
    ...(restock === undefined || restock === null ? {} : { restock: Boolean(restock) }),
  };

  // A till that takes no payments records the exchange and moves nothing.
  if (!rules?.take_payments) return body;

  const kind = settlementKind(Number(diffMinor) || 0);
  if (kind === "pay") {
    const plan = buildTender(rules, fromMinor(Number(diffMinor)), tenderLines);
    if (!plan.ok) throw new Error(plan.message);
    return { ...body, payments: plan.payload.payments };
  }
  if (kind === "refund") {
    // No method = the server gives it back across the tenders the sale actually collected.
    return { ...body, ...(refundMethod ? { refundMethod } : {}) };
  }
  return body;
}

/**
 * What the server says it did with the money, in the shop's words. The screen prints THIS, never a
 * difference it computed itself: only the server knows which tenders the original sale collected
 * and how much of each was still refundable.
 */
export function settlementSummary(result) {
  const amount = Number(result?.settled_amount ?? 0);
  const byMethod = result?.settled_by_method ?? {};
  const uncollected = Number(result?.uncollected ?? 0);
  const methods = Object.entries(byMethod)
    .map(([method, value]) => `${METHOD_LABEL[method] ?? method} ${value}`)
    .join(" · ");
  // A card reversal is promised at the counter and proven at the machine, and a cash-only shop
  // reverses it by hand. Neither is money returned yet, so neither may be announced as refunded.
  const pending = (result?.awaiting_confirmation ?? []).reduce(
    (sum, row) => sum + Number(row.amount ?? 0),
    0,
  );
  const manual = (result?.terminal_only ?? []).reduce(
    (sum, row) => sum + Number(row.amount ?? 0),
    0,
  );
  const parts = [];
  if (result?.settlement === "collected") parts.push(`اتحصّل فرق ${amount.toFixed(2)} ج.م`);
  else if (result?.settlement === "refunded") {
    // ``refunded`` from the server is money that already left the shop or was confirmed on the
    // machine; pending money is reported apart. Subtracting it a second time here turned
    // "50 cash back + 50 pending on the machine" into "0 refunded".
    const confirmed = Number(result?.refunded ?? amount);
    parts.push(`اترد فرق ${confirmed.toFixed(2)} ج.م`);
    if (pending > 0) {
      parts.push(`منها ${pending.toFixed(2)} ج.م لسه مستنية تأكيد الماكينة`);
    }
    if (manual > 0) {
      parts.push(`${manual.toFixed(2)} ج.م يترد يدويًا على الماكينة ويُسجَّل رقم المرجع`);
    }
  }
  else if (result?.settlement === "exchange_only") parts.push("استبدال بدون فرق");
  else parts.push("الفرق مسجّل على الفاتورة فقط (الكاشير مش بيسجّل مدفوعات)");
  if (methods) parts.push(methods);
  if (uncollected > 0) parts.push(`منها ${uncollected.toFixed(2)} ج.م لم تُحصَّل أصلًا فلم تُرَد`);
  return parts.join(" — ");
}

const METHOD_LABEL = {
  cash: "نقدي",
  card: "بطاقة",
  bank_transfer: "تحويل بنكي",
  wallet: "محفظة",
};

/** Backend refusals in plain Arabic; anything unknown is passed through, never hidden. */
export function exchangeErrorMessage(err) {
  const m = String(err?.message ?? err ?? "");
  if (/exchanges ride the open drawer|session is closed/i.test(m)) return "الوردية مغلقة. افتح الوردية أولًا لتسجيل الاستبدال.";
  if (/insufficient|not enough stock|out of stock/i.test(m)) return "الكمية المطلوبة من الصنف البديل غير متوفرة في المخزون.";
  if (/collect the difference/i.test(m)) return "لازم تحصّل فرق السعر قبل إتمام الاستبدال.";
  if (/does not record payments/i.test(m)) return "الكاشير ده مش بيسجّل مدفوعات، فمينفعش يتحصّل أو يترد فرق من هنا.";
  return m ? m : "تعذّر تنفيذ الاستبدال";
}

export { sendReturn as sendExchange } from "./returnPlan";
