/**
 * Pure helpers for the Expenses screen: backend rows <-> screen rows, the same
 * validation the backend enforces (so a bad entry is stopped before the request),
 * totals with integer money math, and Arabic messages for the backend's refusals.
 *
 * The backend rules this mirrors (backend/app/modules/expenses):
 *  - amount: > 0, at most 2 decimals, NEVER rounded (a 3rd decimal is refused).
 *  - a CASH expense is paid from the OPEN shift's drawer; any other method has no shift.
 *  - a posted expense is never edited or deleted: it is VOIDED, with a reason.
 */
import { shopToday } from "@/cashier/lib/period";
import { isWireMoney, sumMoney, toMinor, toWire } from "./money";

export const EXPENSE_METHODS = ["cash", "card", "wallet", "bank_transfer"];
export const MAX_DESCRIPTION = 255;
export const MAX_REASON = 255;

/** Backend category -> { id, name }. Inactive ones are never offered. */
export function categoriesFromApi(list) {
  return (Array.isArray(list) ? list : []).filter((c) => c && c.is_active !== false).map((c) => ({ id: String(c.id), name: String(c.name) }));
}

/** Backend expense -> the row shape the table already renders. */
export function expenseFromApi(e, { categories = [], users = {} } = {}) {
  const cat = categories.find((c) => c.id === e.category_id);
  return {
    id: String(e.id),
    number: e.number,
    date: e.expense_date,
    createdAt: e.created_at ?? e.expense_date,
    categoryId: e.category_id,
    category: cat?.name ?? "—",
    description: e.description,
    amount: e.amount, // stays the backend's exact decimal TEXT ("45.50")
    payment: e.payment_method,
    employee: users[e.created_by_user_id] ?? "—",
    sessionId: e.session_id ?? null,
    status: e.status,
    voided: e.status === "voided",
    voidReason: e.void_reason ?? "",
  };
}

export function expensesFromApi(payload, ctx) {
  const items = Array.isArray(payload) ? payload : (payload?.items ?? []);
  return items.map((e) => expenseFromApi(e, ctx));
}

/** Money text -> a valid wire amount, or null. Accepts Arabic-Indic digits and a decimal comma. */
export function normalizeAmountInput(raw) {
  if (raw === null || raw === undefined) return null;
  const latin = String(raw)
    .trim()
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace("٫", ".")
    .replace(",", ".");
  if (!isWireMoney(latin)) return null;
  // toWire() normalises to exactly 2 places ("45.5" -> "45.50"); a zero amount is never an expense.
  return toMinor(latin) > 0 ? toWire(latin) : null;
}

/**
 * Validate a new expense. Returns { ok:true, payload } or { ok:false, error }.
 */
export function buildExpense(form) {
  if (!form.categoryId) return { ok: false, error: "اختر التصنيف" };
  const description = String(form.description ?? "").trim();
  if (!description) return { ok: false, error: "اكتب بيان المصروف" };
  if (description.length > MAX_DESCRIPTION) return { ok: false, error: `البيان أطول من ${MAX_DESCRIPTION} حرفًا` };
  const amount = normalizeAmountInput(form.amount);
  if (!amount) return { ok: false, error: "المبلغ لازم يكون رقمًا أكبر من صفر وبحد أقصى خانتين عشريتين" };
  if (!EXPENSE_METHODS.includes(form.payment)) return { ok: false, error: "اختر طريقة الدفع" };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(form.date ?? ""))) return { ok: false, error: "اختر تاريخ المصروف" };
  return {
    ok: true,
    payload: {
      category_id: form.categoryId,
      description,
      amount,
      payment_method: form.payment,
      expense_date: form.date,
      // An expense is a record, never a drawer movement: it carries no shift, open or not.
    },
  };
}

export function buildVoid(reason) {
  const text = String(reason ?? "").trim();
  if (!text) return { ok: false, error: "اكتب سبب الإلغاء" };
  if (text.length > MAX_REASON) return { ok: false, error: `السبب أطول من ${MAX_REASON} حرفًا` };
  return { ok: true, payload: { reason: text } };
}

/** Totals over what is still in force. A voided expense is shown but never counted. */
export function summarize(rows, { today } = {}) {
  const live = rows.filter((r) => !r.voided);
  const byCategory = new Map();
  for (const r of live) byCategory.set(r.category, [...(byCategory.get(r.category) ?? []), r.amount]);
  let top = null;
  for (const [name, amounts] of byCategory) {
    const total = sumMoney(amounts);
    if (!top || toMinor(total) > toMinor(top.amount)) top = { name, amount: total };
  }
  const day = today ?? shopToday();
  return {
    total: sumMoney(live.map((r) => r.amount)),
    count: live.length,
    today: sumMoney(live.filter((r) => String(r.date).slice(0, 10) === day).map((r) => r.amount)),
    cash: sumMoney(live.filter((r) => r.payment === "cash").map((r) => r.amount)),
    top: top?.name ?? "—",
    topAmount: top?.amount ?? "0.00",
    voidedCount: rows.length - live.length,
  };
}

/** Search + filters. The search also matches the category and the employee, like the old screen. */
export function filterExpenses(rows, { term = "", category = "", payment = "", showVoided = true } = {}) {
  const t = term.trim().toLowerCase();
  return rows.filter((e) => {
    if (!showVoided && e.voided) return false;
    if (t && ![e.number, e.description, e.category, e.employee].some((v) => String(v ?? "").toLowerCase().includes(t))) return false;
    if (category && e.category !== category) return false;
    if (payment && e.payment !== payment) return false;
    return true;
  });
}

/** The backend's refusal -> one clear Arabic sentence. Unknown errors keep their own text. */
export function expenseErrorMessage(err) {
  const status = err?.status;
  const text = String(err?.detail ?? err?.message ?? "");
  if (/already voided/i.test(text)) return "المصروف ده اتلغى قبل كده";
  if (/shift that paid this expense is closed/i.test(text))
    return "الوردية اللي دفعت المصروف ده اتقفلت. سجّل التصحيح في الوردية الحالية";
  if (/open a shift|OPEN shift/i.test(text)) return "المصروف النقدي محتاج وردية مفتوحة";
  if (/inactive/i.test(text)) return "التصنيف ده موقوف";
  if (/2 decimal/i.test(text)) return "المبلغ فيه أكتر من خانتين عشريتين";
  if (status === 403) return "مش مسموح لك بالعملية دي. لازم صلاحية مدير";
  if (status === 404) return "المصروف أو التصنيف مش موجود";
  if (status === 0 || status >= 500) return "تعذّر الاتصال بالخادم. جرّب تاني";
  return text || "حصل خطأ غير متوقع";
}
