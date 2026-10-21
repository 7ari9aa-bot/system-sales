/**
 * Pure helpers for the purchasing screens (suppliers, purchase orders, supplier returns).
 *
 * What the old mock screens got wrong, and this layer fixes:
 *  - ONE status mixed two different facts ("received" meant "fully paid"). Receiving the goods and paying for
 *    them are separate: the shop usually receives first and pays later. Here the receipt state
 *    (draft / received / cancelled) and the payment state (unpaid / partial / paid) are shown apart.
 *  - money was summed with floats and toFixed(2). Everything here goes through the integer-cent helpers.
 *
 * The backend rules this mirrors (backend/app/modules/purchasing): a quantity is a whole number > 0 ("1e3" is
 * refused), a unit cost has at most 2 decimals (0 is allowed: a free line), a variant appears once per document,
 * a cash payment needs an open shift, a payment cannot exceed what is still owed.
 */
import { isWireMoney, mulMoney, sumMoney, toMinor, toWire } from "./money";

export const PAYMENT_METHODS = ["cash", "card", "wallet", "bank_transfer"];
export const RETURN_SETTLEMENTS = ["credit", "cash", "replace"];

export const RECEIPT_LABEL = { draft: "مسودة", received: "مستلمة", cancelled: "ملغاة" };
export const PAYMENT_LABEL = { unpaid: "غير مدفوعة", partial: "مدفوعة جزئيًا", paid: "مدفوعة بالكامل" };
export const RETURN_STATUS_LABEL = { review: "بانتظار المورد", accepted: "مقبول", rejected: "مرفوض" };
export const SETTLEMENT_LABEL = { credit: "خصم من الحساب", cash: "استرداد نقدي", replace: "استبدال" };

const WHOLE = /^\d+(\.0+)?$/;

/** A quantity typed by a person -> a positive integer, or null. "1e3", "2.5", "-1", "" are all refused. */
export function parseQuantity(raw) {
  const latin = String(raw ?? "")
    .trim()
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
  if (!WHOLE.test(latin)) return null;
  const n = Number(latin);
  return Number.isSafeInteger(n) && n > 0 && n <= 1_000_000 ? n : null;
}

/** A cost typed by a person -> wire text with 2 places, or null. Unlike a payment, ZERO is a valid cost. */
export function parseCost(raw) {
  if (raw === null || raw === undefined) return null;
  const latin = String(raw)
    .trim()
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace("٫", ".")
    .replace(",", ".");
  return isWireMoney(latin) ? toWire(latin) : null;
}

/** A payment amount: like a cost but strictly positive. */
export function parsePayment(raw) {
  const wire = parseCost(raw);
  return wire && toMinor(wire) > 0 ? wire : null;
}

/** Line total in exact cents: "12.50" x 3 = "37.50". */
export const lineTotal = (qty, unitCost) => mulMoney(unitCost, qty);

/** Add a line, or merge into an existing one for the same variant (the backend refuses a duplicate variant). */
export function addLine(lines, { variantId, label, qty, unitCost }) {
  const q = parseQuantity(qty);
  if (!q) return { ok: false, error: "الكمية لازم تكون رقمًا صحيحًا أكبر من صفر" };
  const cost = parseCost(unitCost);
  if (!cost) return { ok: false, error: "سعر الشراء لازم يكون رقمًا بحد أقصى خانتين عشريتين" };
  if (!variantId) return { ok: false, error: "اختر الصنف" };
  const at = lines.findIndex((l) => l.variantId === variantId);
  if (at >= 0) {
    const merged = lines[at].qty + q;
    // Same variant bought twice at two prices cannot share one line: keep it honest instead of averaging silently.
    if (toMinor(lines[at].unitCost) !== toMinor(cost)) {
      return { ok: false, error: "الصنف ده مضاف بسعر مختلف. عدّل البند الموجود بدل ما تضيفه مرتين" };
    }
    if (merged > 1_000_000) return { ok: false, error: "الكمية كبيرة جدًا" };
    const next = [...lines];
    next[at] = { ...lines[at], qty: merged, total: lineTotal(merged, cost) };
    return { ok: true, lines: next };
  }
  return { ok: true, lines: [...lines, { variantId, label, qty: q, unitCost: cost, total: lineTotal(q, cost) }] };
}

export const linesTotal = (lines) => sumMoney(lines.map((l) => l.total));
export const piecesOf = (lines) => lines.reduce((s, l) => s + l.qty, 0);

/** Validate a new purchase order. { ok, payload } | { ok:false, error }. */
export function buildPurchaseOrder(form) {
  if (!form.supplierId) return { ok: false, error: "اختر المورد" };
  if (!form.lines?.length) return { ok: false, error: "أضف بندًا واحدًا على الأقل قبل الحفظ" };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(form.date ?? ""))) return { ok: false, error: "اختر تاريخ الفاتورة" };
  const note = String(form.note ?? "").trim();
  if (note.length > 255) return { ok: false, error: "الملاحظة أطول من 255 حرفًا" };
  return {
    ok: true,
    payload: {
      supplier_id: form.supplierId,
      order_date: form.date,
      // The till records goods that ALREADY arrived. A draft is a separate, later feature.
      receive_now: form.receiveNow !== false,
      ...(note ? { note } : {}),
      ...(form.warehouseId ? { warehouse_id: form.warehouseId } : {}),
      lines: form.lines.map((l) => ({ variant_id: l.variantId, quantity: String(l.qty), unit_cost: l.unitCost })),
    },
  };
}

/** Validate a payment to a supplier. `owed` is the order's remaining balance (wire text) or null. */
export function buildPayment(form, { openSessionId = null, owed = null } = {}) {
  if (!form.supplierId) return { ok: false, error: "اختر المورد" };
  const amount = parsePayment(form.amount);
  if (!amount) return { ok: false, error: "المبلغ لازم يكون رقمًا أكبر من صفر وبحد أقصى خانتين عشريتين" };
  if (!PAYMENT_METHODS.includes(form.method)) return { ok: false, error: "اختر طريقة الدفع" };
  if (owed !== null && toMinor(amount) > toMinor(owed)) {
    return { ok: false, error: `المبلغ أكبر من المتبقي على الفاتورة (${owed})` };
  }
  if (form.method === "cash" && !openSessionId) {
    return { ok: false, error: "الدفع النقدي بيطلع من درج الوردية: افتح وردية الأول أو اختر طريقة دفع تانية" };
  }
  const note = String(form.note ?? "").trim();
  return {
    ok: true,
    payload: {
      supplier_id: form.supplierId,
      amount,
      method: form.method,
      ...(form.orderId ? { purchase_order_id: form.orderId } : {}),
      ...(form.method === "cash" ? { session_id: openSessionId } : {}),
      ...(note ? { note } : {}),
    },
  };
}

/** Validate a supplier return. Without an order the price must be typed; with one the order's price is used. */
export function buildReturn(form) {
  if (!form.supplierId) return { ok: false, error: "اختر المورد" };
  if (!RETURN_SETTLEMENTS.includes(form.settlement)) return { ok: false, error: "اختر طريقة التسوية" };
  if (!form.lines?.length) return { ok: false, error: "أضف بندًا واحدًا على الأقل" };
  const lines = [];
  for (const [i, l] of form.lines.entries()) {
    const qty = parseQuantity(l.qty);
    if (!qty) return { ok: false, error: `البند ${i + 1}: الكمية لازم تكون رقمًا صحيحًا أكبر من صفر` };
    const line = { variant_id: l.variantId, quantity: String(qty) };
    if (!form.orderId) {
      const cost = parseCost(l.unitCost);
      if (!cost) return { ok: false, error: `البند ${i + 1}: اكتب سعر الشراء` };
      line.unit_cost = cost;
    }
    lines.push(line);
  }
  const note = String(form.note ?? "").trim();
  return {
    ok: true,
    payload: {
      supplier_id: form.supplierId,
      settlement: form.settlement,
      lines,
      ...(form.orderId ? { purchase_order_id: form.orderId } : {}),
      ...(note ? { note } : {}),
    },
  };
}

/* ------------------------------------------------------------- mapping */

export function supplierFromApi(s) {
  const st = s.statement ?? null;
  return {
    id: s.id,
    name: s.name,
    company: s.company ?? "",
    agent: s.contact_name ?? "",
    phone: s.phone ?? "",
    city: s.city ?? "",
    status: s.status,
    // All derived by the backend from documents, never stored: nothing here can drift.
    total: st?.total_supplied ?? "0.00",
    ordersCount: st?.orders_count ?? 0,
    lastDeal: st?.last_order_date ?? null,
    items: st?.items_count ?? 0,
    paid: st?.paid ?? "0.00",
    credit: st?.credit_returns ?? "0.00",
    balance: st?.balance ?? "0.00",
  };
}

export function orderFromApi(o, { suppliers = {}, variants = {} } = {}) {
  const items = (o.lines ?? []).map((l) => ({
    variantId: l.variant_id,
    name: variants[l.variant_id]?.productName ?? "—",
    color: variants[l.variant_id]?.color ?? "",
    size: variants[l.variant_id]?.size ?? "",
    qty: l.quantity,
    unitCost: l.unit_cost,
    total: l.line_total,
  }));
  return {
    id: o.id,
    number: o.number,
    date: o.order_date,
    supplierId: o.supplier_id,
    supplierName: suppliers[o.supplier_id] ?? "—",
    items,
    pieces: items.reduce((s, i) => s + i.qty, 0),
    total: o.total,
    paid: o.paid,
    balance: o.balance,
    receipt: o.status, // draft | received | cancelled
    payment: o.payment_status, // unpaid | partial | paid
    note: o.note ?? "",
    warehouseId: o.warehouse_id,
  };
}

export function returnFromApi(r, { suppliers = {}, variants = {}, orders = {} } = {}) {
  const items = (r.lines ?? []).map((l) => ({
    variantId: l.variant_id,
    name: variants[l.variant_id]?.productName ?? "—",
    color: variants[l.variant_id]?.color ?? "",
    size: variants[l.variant_id]?.size ?? "",
    qty: l.quantity,
    unitCost: l.unit_cost,
    total: l.line_total,
  }));
  return {
    id: r.id,
    number: r.number,
    date: r.return_date,
    supplierId: r.supplier_id,
    supplierName: suppliers[r.supplier_id] ?? "—",
    orderId: r.purchase_order_id ?? null,
    poNumber: orders[r.purchase_order_id] ?? "—",
    settlement: r.settlement,
    status: r.status,
    amount: r.total,
    qty: items.reduce((s, i) => s + i.qty, 0),
    items,
    note: r.note ?? "",
  };
}

/* ------------------------------------------------------------- summaries */

/** Orders summary. A cancelled/draft order owes nothing and is not "supplied": only received ones count. */
export function purchasesSummary(rows) {
  const live = rows.filter((r) => r.receipt === "received");
  return {
    count: rows.length,
    receivedCount: live.length,
    total: sumMoney(live.map((r) => r.total)),
    paid: sumMoney(live.map((r) => r.paid)),
    balance: sumMoney(live.map((r) => r.balance)),
    pieces: live.reduce((s, r) => s + r.pieces, 0),
    unpaidCount: live.filter((r) => r.payment !== "paid").length,
  };
}

export function suppliersSummary(rows) {
  return {
    count: rows.length,
    active: rows.filter((r) => r.status === "active").length,
    total: sumMoney(rows.map((r) => r.total)),
    // What the shop owes. A supplier in credit (negative) is NOT netted against another's debt in this number.
    owed: sumMoney(rows.filter((r) => toMinor(r.balance) > 0).map((r) => r.balance)),
    inCredit: sumMoney(rows.filter((r) => toMinor(r.balance) < 0).map((r) => r.balance)),
  };
}

/** Returns summary: money only counts once the supplier accepted it. */
export function returnsSummary(rows) {
  const accepted = rows.filter((r) => r.status === "accepted");
  const by = (settlement) => sumMoney(accepted.filter((r) => r.settlement === settlement).map((r) => r.amount));
  return {
    count: rows.length,
    qty: rows.reduce((s, r) => s + r.qty, 0),
    review: rows.filter((r) => r.status === "review").length,
    pendingAmount: sumMoney(rows.filter((r) => r.status === "review").map((r) => r.amount)),
    credit: by("credit"),
    cash: by("cash"),
  };
}

export function filterOrders(rows, { term = "", supplierId = "", receipt = "", payment = "" } = {}) {
  const t = term.trim().toLowerCase();
  return rows.filter((r) => {
    if (t && !(r.number.toLowerCase().includes(t) || r.supplierName.toLowerCase().includes(t))) return false;
    if (supplierId && r.supplierId !== supplierId) return false;
    if (receipt && r.receipt !== receipt) return false;
    if (payment && r.payment !== payment) return false;
    return true;
  });
}

/** The backend's refusal -> one clear Arabic sentence. Unknown errors keep their own text. */
export function purchasingErrorMessage(err) {
  const status = err?.status;
  const text = String(err?.detail ?? err?.message ?? "");
  if (/already received/i.test(text)) return "الفاتورة دي اتسجلت كمستلمة قبل كده";
  if (/supplier return instead/i.test(text)) return "الفاتورة المستلمة ما تتلغيش. سجّل مرتجع للمورد بدلها";
  if (/more than what is still owed/i.test(text)) return "المبلغ أكبر من المتبقي على الفاتورة";
  if (/open a shift|OPEN shift/i.test(text)) return "الدفع النقدي محتاج وردية مفتوحة";
  if (/still returnable/i.test(text)) return "الكمية المرتجعة أكبر من المتاح للإرجاع على الفاتورة دي";
  if (/already (accepted|rejected)/i.test(text)) return "المرتجع ده اتحسم قبل كده";
  if (/already exists/i.test(text)) return "فيه مورد بنفس الاسم";
  if (/inactive/i.test(text)) return "المورد ده موقوف";
  if (/insufficient|cannot|below zero/i.test(text) && /stock/i.test(text)) return "المخزون الحالي أقل من الكمية المرتجعة";
  if (/Idempotency-Key reused/i.test(text)) return "الطلب اتبعت بنفس المفتاح ببيانات مختلفة. جرّب تاني";
  if (status === 403) return "مش مسموح لك بالعملية دي. لازم صلاحية مدير";
  if (status === 404) return "العنصر مش موجود";
  if (status === 0 || status >= 500) return "تعذّر الاتصال بالخادم. جرّب تاني";
  return text || "حصل خطأ غير متوقع";
}
