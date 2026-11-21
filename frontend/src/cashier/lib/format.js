// Shared number / date formatting for the whole system (Arabic labels).

import { currencyLabel } from "./receiptShop";

// The Egyptian pound until the signed-in shop says otherwise. A shop trades in ONE currency (the
// server's ``Tenant.currency``), so one module-level sign serves every amount on every screen
// without threading a prop through each of them.
const DEFAULT_CURRENCY = "ج.م";
let CURRENCY = DEFAULT_CURRENCY;

/** Set the sign every amount is written with, from the shop's ISO code. A code that cannot be read keeps the last good sign. */
export function setShopCurrency(code) {
  CURRENCY = currencyLabel(code) || DEFAULT_CURRENCY;
}

/** The sign amounts are written with right now (for the few places that write one beside a number). */
export function currencySign() {
  return CURRENCY;
}

// A figure that rounds to nothing must read as nothing: -0.004 at two places is "0.00", not "-0.00"
// (JavaScript keeps the sign of a negative that rounds to zero, and so does a literal -0).
function groupedNumber(n, digits) {
  const text = n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return /^-[0.,]*$/.test(text) ? text.slice(1) : text;
}

export function fmtMoney(value) {
  const n = Number(value) || 0;
  return `${groupedNumber(n, 2)} ${CURRENCY}`;
}

/** An amount taken out of the drawer (returns, a deduction): a minus sign only when it is not nothing.
 * A return of -0.004 rounds to 0.00, and a bare `−${fmtMoney(...)}` wrote "−0.00" for it. */
export function fmtMoneyDeduction(value) {
  const body = fmtMoney(Math.abs(Number(value) || 0));
  return body.startsWith("0.00 ") ? body : `−${body}`;
}

/** A figure that may be unknown (null/undefined): "—" instead of a zero that looks like a real amount. */
export function fmtMoneyOrDash(value) {
  return value === null || value === undefined ? "—" : fmtMoney(value);
}

export function fmtMoneyShort(value) {
  const n = Number(value) || 0;
  return groupedNumber(n, 0);
}

export function fmtNumber(value, digits = 2) {
  const n = Number(value) || 0;
  return groupedNumber(n, digits);
}

export function fmtInt(value) {
  const n = Number(value) || 0;
  const text = n.toLocaleString("en-US");
  return text === "-0" ? "0" : text;
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("ar-EG", { day: "2-digit", month: "2-digit", year: "numeric" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${date} - ${time}`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("ar-EG", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** The calendar day (YYYY-MM-DD) of an instant in the viewer's local time, for the date filters. */
export function localDay(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// Arabic labels for the shared status / type vocabularies.
export const INVOICE_STATUS = {
  paid: { label: "مسجّلة", tone: "success" }, // internal key kept; the POS records the sale, it never takes payment
  partial_return: { label: "مرتجع جزئي", tone: "warning" },
  returned: { label: "مرتجعة", tone: "danger" },
  suspended: { label: "معلقة", tone: "neutral" },
  cancelled: { label: "ملغاة", tone: "danger" },
};

export const PAYMENT_METHODS = {
  cash: { label: "نقدي", tone: "success" },
  card: { label: "بطاقة", tone: "info" },
  wallet: { label: "محفظة إلكترونية", tone: "violet" },
  credit: { label: "آجل", tone: "warning" },
  bank_transfer: { label: "تحويل بنكي", tone: "info" },
  mixed: { label: "مقسّم", tone: "violet" },
};

export const INVENTORY_STATUS = {
  in: { label: "متوفر", tone: "success" },
  low: { label: "منخفض", tone: "warning" },
  out: { label: "نافد", tone: "danger" },
};

export const PRODUCT_STATUS = {
  active: { label: "نشط", tone: "success" },
  inactive: { label: "متوقف", tone: "neutral" },
};

export const MOVEMENT_TYPES = {
  purchase: { label: "توريد", tone: "info" },
  sale: { label: "بيع", tone: "success" },
  return: { label: "مرتجع عميل", tone: "danger" },
  adjustment: { label: "تسوية جرد", tone: "warning" },
  supplier_return: { label: "مرتجع لمورد", tone: "danger" },
  supplier_return_reversal: { label: "إلغاء مرتجع مورد", tone: "info" },
  transfer_in: { label: "تحويل وارد", tone: "neutral" },
  transfer_out: { label: "تحويل صادر", tone: "neutral" },
  damage: { label: "تالف", tone: "danger" },
};

export const RETURN_STATUS = {
  completed: { label: "مكتمل", tone: "success" },
  review: { label: "قيد المراجعة", tone: "warning" },
};

export const EXCHANGE_STATUS = {
  completed: { label: "مكتمل", tone: "success" },
  review: { label: "قيد المراجعة", tone: "warning" },
};

export const REFUND_METHODS = {
  cash: { label: "نقدي", tone: "success" },
  card: { label: "بطاقة", tone: "info" },
  wallet: { label: "محفظة إلكترونية", tone: "violet" },
  balance: { label: "رصيد للعميل", tone: "primary" },
};

export const SETTLEMENT_TYPES = {
  collected: { label: "تحصيل فرق", tone: "violet" },
  refunded: { label: "رد فرق", tone: "danger" },
  even: { label: "بدون فرق", tone: "neutral" },
};

export const SUPPLIER_STATUS = {
  active: { label: "نشط", tone: "success" },
  inactive: { label: "متوقف", tone: "neutral" },
};

export const SUPPLIER_RETURN_SETTLEMENTS = {
  cash: { label: "استرداد نقدي", tone: "success" },
  credit: { label: "خصم من الحساب", tone: "info" },
  replace: { label: "استبدال بضاعة", tone: "violet" },
};

export const SHIFT_STATUS = {
  open: { label: "مفتوحة", tone: "success" },
  closed: { label: "مغلقة", tone: "neutral" },
};

export const ACTIVITY_TYPES = {
  sale: { label: "فاتورة بيع", tone: "success" },
  return: { label: "مرتجع عميل", tone: "danger" },
  purchase: { label: "توريد", tone: "info" },
  supplier_return: { label: "مرتجع مورد", tone: "primary" },
  supplier_payment: { label: "دفعة مورد", tone: "violet" },
  expense: { label: "مصروف", tone: "warning" },
  inventory: { label: "حركة مخزون", tone: "neutral" },
  shift: { label: "وردية", tone: "info" },
};

export const BACKUP_STATUS = {
  completed: { label: "مكتملة", tone: "success" },
  running: { label: "قيد الإنشاء", tone: "info" },
  failed: { label: "فاشلة", tone: "danger" },
};

export const BACKUP_TYPES = {
  manual: { label: "يدوي", tone: "primary" },
  auto: { label: "تلقائي", tone: "violet" },
};