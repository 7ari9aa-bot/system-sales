// Shared number / date formatting for the whole system (Egyptian pound, Arabic labels).

const CURRENCY = "ج.م";

export function fmtMoney(value) {
  const n = Number(value) || 0;
  return `${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${CURRENCY}`;
}

export function fmtMoneyShort(value) {
  const n = Number(value) || 0;
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function fmtNumber(value, digits = 2) {
  const n = Number(value) || 0;
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(value) {
  return (Number(value) || 0).toLocaleString("en-US");
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

export function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// Arabic labels for the shared status / type vocabularies.
export const INVOICE_STATUS = {
  paid: { label: "مدفوعة", tone: "success" },
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
  return: { label: "مرتجع", tone: "danger" },
  exchange: { label: "استبدال", tone: "violet" },
  transfer: { label: "تحويل مخزن", tone: "neutral" },
  adjustment: { label: "تسوية جرد", tone: "warning" },
};

export const REASON_LABELS = [
  "المقاس غير مناسب",
  "اللون مختلف عن المتوقع",
  "عيب في المنتج",
  "العميل غيّر رأيه",
  "استبدال بمقاس آخر",
  "استبدال بموديل آخر",
];

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

export const SUPPLIER_RETURN_REASONS = [
  "عيب تصنيع",
  "بضاعة تالفة عند الاستلام",
  "مقاسات خاطئة من المورد",
  "لون مختلف عن المعروض",
  "خامة أقل من الاتفاق",
  "فائض عن الحاجة",
];

export const SHIFT_STATUS = {
  open: { label: "مفتوحة", tone: "success" },
  closed: { label: "مغلقة", tone: "neutral" },
};

export const ACTIVITY_TYPES = {
  sale: { label: "فاتورة بيع", tone: "success" },
  sale_hold: { label: "فاتورة معلقة", tone: "warning" },
  return: { label: "مرتجع عميل", tone: "danger" },
  exchange: { label: "استبدال", tone: "violet" },
  purchase: { label: "توريد", tone: "info" },
  supplier_return: { label: "مرتجع مورد", tone: "primary" },
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