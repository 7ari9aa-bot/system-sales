/**
 * How a sale is paid, built to the rules the server enforces (pos/tender.py::settle).
 *
 * The till's own rules (`tender` on the day state) say whether it records payments at all. When
 * it does not, nothing here adds a payment, and the sale goes out exactly as before. When it
 * does, the server refuses a sale whose lines do not cover the total, so this refuses the same
 * things first, in Arabic, before any request: no line, a method the till does not accept, a
 * missing reference, an amount that is zero, negative or not a number, paying more than the total,
 * cash handed over below what it covers.
 *
 * A sale on the customer's account is the one case where the lines may cover LESS than the total
 * (the rest is posted to the customer's ledger), even nothing at all. It needs a named customer.
 */
import { addMoney, fromMinor, subMoney, toMinor, toWire } from "./money";

const digits = (v) =>
  String(v ?? "")
    .trim()
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace("٫", ".")
    .replace(",", ".");

const fail = (message) => ({ ok: false, message });

/** A non-negative amount of at most two decimals as wire text, or null. */
function amountOf(raw) {
  const text = digits(raw);
  if (text === "" || !/^\d+(\.\d{1,2})?$/.test(text)) return null;
  return toWire(text);
}

export function defaultTender(rules, total) {
  if (!rules?.take_payments || !rules.methods?.length) return [];
  return [{ method: rules.methods[0], amount: String(total), tendered: "", reference: "" }];
}

export function canSellOnAccount(rules, { customerId, customerPhone } = {}) {
  if (!rules?.take_payments || !rules.allow_on_account) return false;
  return Boolean(customerId) || String(customerPhone ?? "").trim() !== "";
}

/** Why a sale cannot be queued offline, or null. A till that records payments cannot settle one later. */
export function offlineTenderBlocked(rules) {
  return rules?.take_payments ? "الكاشير ده بيسجّل طرق الدفع، فمينفعش يتسجل بيع من غير نت. استنى لحد ما النت يرجع." : null;
}

export function buildTender(rules, total, lines, { onAccount = false } = {}) {
  if (!rules?.take_payments) return { ok: true, payload: {} };
  if (onAccount && !rules.allow_on_account) return fail("البيع الآجل مش مفعّل على الكاشير ده.");

  const allowed = new Set(rules.methods ?? []);
  const needsRef = new Set(rules.reference_required ?? []);
  const wire = [];
  let paid = "0.00";
  for (const line of lines ?? []) {
    if (!allowed.has(line.method)) return fail("طريقة الدفع دي مش مفعّلة على الكاشير ده.");
    const amount = amountOf(line.amount);
    if (amount === null || toMinor(amount) <= 0) return fail("اكتب مبلغ صحيح أكبر من صفر لكل طريقة دفع.");
    const out = { method: line.method, amount };
    const ref = String(line.reference ?? "").trim();
    if (needsRef.has(line.method)) {
      if (!ref) return fail("طريقة الدفع دي محتاجة رقم مرجعي (رقم الموافقة أو التحويل).");
      out.reference = ref;
    }
    const handed = String(line.tendered ?? "").trim();
    if (handed !== "") {
      const tendered = amountOf(handed);
      if (tendered === null) return fail("المبلغ المستلم لازم يكون رقم صحيح.");
      if (line.method !== "cash") {
        if (toMinor(tendered) !== toMinor(amount)) return fail("المستلم أكتر من المبلغ مسموح في الكاش بس.");
      } else if (toMinor(tendered) < toMinor(amount)) {
        return fail("المبلغ المستلم أقل من المبلغ المطلوب.");
      } else if (toMinor(tendered) > toMinor(amount)) {
        out.tendered = tendered;
      }
    }
    paid = addMoney(paid, amount);
    wire.push(out);
  }

  const totalMinor = toMinor(total);
  const paidMinor = toMinor(paid);
  if (paidMinor > totalMinor) return fail("المدفوع أكبر من إجمالي الفاتورة.");
  if (!onAccount) {
    if (!wire.length) return fail("اختار طريقة دفع واحدة على الأقل.");
    if (paidMinor < totalMinor) return fail(`المدفوع أقل من الإجمالي بـ ${subMoney(total, paid)}.`);
  }
  const payload = {};
  if (wire.length) payload.payments = wire;
  if (onAccount) payload.on_account = true;
  return { ok: true, payload };
}

/** What is still to be covered by the lines entered so far. Never negative; a half-typed line counts as nothing. */
export function remainingToPay(total, lines) {
  let paid = "0.00";
  for (const line of lines ?? []) {
    const amount = amountOf(line.amount);
    if (amount !== null) paid = addMoney(paid, amount);
  }
  return toMinor(total) > toMinor(paid) ? subMoney(total, paid) : "0.00";
}

/** The change owed to the customer: cash handed over above the cash amount it covers. */
export function changeDue(lines) {
  let minor = 0;
  for (const line of lines ?? []) {
    if (line.method !== "cash") continue;
    const amount = amountOf(line.amount);
    const handed = amountOf(line.tendered);
    if (amount !== null && handed !== null && toMinor(handed) > toMinor(amount)) minor += toMinor(handed) - toMinor(amount);
  }
  return fromMinor(minor);
}

/** The dialog's answer as the sale takes it. A till that records no payment answers with nothing. */
export const saleTender = (answer) => ({ payments: answer?.payments, onAccount: answer?.on_account });

/** Whether a sale can be queued now that the connection is down, and why not. */
export function whenOffline(rules) {
  const blocked = offlineTenderBlocked(rules);
  return blocked ? { queue: false, message: blocked } : { queue: true };
}
