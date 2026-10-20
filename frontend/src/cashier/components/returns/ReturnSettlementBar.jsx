import { fmtMoney, REASON_LABELS, REFUND_METHODS } from "@/cashier/lib/format";

const SELECT =
  "h-7 rounded-md border border-border bg-card px-1.5 text-[12px] font-semibold text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring";

// ملخص أسفل جدول المرتجع: قيمة المرتجع، سبب الاسترجاع، طريقة الاسترداد، ثم المستحق للعميل.
export default function ReturnSettlementBar({ value, reason, onReasonChange, refundMethod, onRefundMethodChange }) {
  return (
    <div className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة المرتجع</p>
        <p className="num font-heading text-[15px] font-bold text-rose-600">{fmtMoney(value)}</p>
      </div>

      <label className="flex flex-col gap-0.5">
        <span className="text-[12px] font-semibold text-foreground/70">سبب الاسترجاع</span>
        <select value={reason} onChange={(e) => onReasonChange(e.target.value)} className={SELECT} aria-label="سبب الاسترجاع">
          <option value="">اختر السبب</option>
          {REASON_LABELS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-0.5">
        <span className="text-[12px] font-semibold text-foreground/70">طريقة الاسترداد</span>
        <select
          value={refundMethod}
          onChange={(e) => onRefundMethodChange(e.target.value)}
          className={SELECT}
          aria-label="طريقة الاسترداد"
        >
          {Object.entries(REFUND_METHODS).map(([key, method]) => (
            <option key={key} value={key}>
              {method.label}
            </option>
          ))}
        </select>
      </label>

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">المستحق للعميل</p>
        <p className="num font-heading text-lg font-extrabold text-emerald-600">{fmtMoney(value)}</p>
      </div>
    </div>
  );
}