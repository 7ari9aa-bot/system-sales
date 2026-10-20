import { cn } from "@/cashier/lib/utils";
import {
  ACTIVITY_TYPES,
  BACKUP_STATUS,
  BACKUP_TYPES,
  EXCHANGE_STATUS,
  INVENTORY_STATUS,
  INVOICE_STATUS,
  MOVEMENT_TYPES,
  PAYMENT_METHODS,
  PRODUCT_STATUS,
  REFUND_METHODS,
  RETURN_STATUS,
  SETTLEMENT_TYPES,
  SHIFT_STATUS,
  SUPPLIER_RETURN_SETTLEMENTS,
  SUPPLIER_STATUS,
} from "@/cashier/lib/format";

const TONES = {
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  warning: "bg-amber-50 text-amber-700 ring-amber-200",
  danger: "bg-rose-50 text-rose-700 ring-rose-200",
  info: "bg-sky-50 text-sky-700 ring-sky-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
  neutral: "bg-slate-100 text-slate-600 ring-slate-200",
  primary: "bg-orange-50 text-orange-700 ring-orange-200",
};

const MAPS = {
  invoice: INVOICE_STATUS,
  payment: PAYMENT_METHODS,
  inventory: INVENTORY_STATUS,
  product: PRODUCT_STATUS,
  movement: MOVEMENT_TYPES,
  return: RETURN_STATUS,
  exchange: EXCHANGE_STATUS,
  refund: REFUND_METHODS,
  settlement: SETTLEMENT_TYPES,
  supplier: SUPPLIER_STATUS,
  supplier_return: SUPPLIER_RETURN_SETTLEMENTS,
  shift: SHIFT_STATUS,
  activity: ACTIVITY_TYPES,
  backup: BACKUP_STATUS,
  backup_type: BACKUP_TYPES,
};

const FALLBACK = {
  paid: { label: "مدفوع", tone: "success" },
  unpaid: { label: "غير مدفوع", tone: "danger" },
  partial: { label: "مدفوع جزئياً", tone: "warning" },
  received: { label: "مستلم", tone: "success" },
  pending: { label: "قيد التنفيذ", tone: "warning" },
};

// شارة حالة موحّدة لكل مستندات وأصناف النظام.
export default function StatusBadge({ kind = "invoice", value, label, className }) {
  const entry = MAPS[kind]?.[value] ?? FALLBACK[value] ?? { label: label ?? value ?? "—", tone: "neutral" };
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1",
        TONES[entry.tone] ?? TONES.neutral,
        className,
      )}
    >
      {label ?? entry.label}
    </span>
  );
}