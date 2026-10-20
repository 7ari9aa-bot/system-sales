import { fmtMoney } from "@/cashier/lib/format";

// ملخص أسفل جدول المرتجع. الخادم يرد المبلغ على طريقة الدفع الأصلية للفاتورة (لا نختارها هنا)،
// والقيمة المعروضة تقدير بنفس معادلة الخادم، والنهائي يأتي منه بعد الاعتماد.
export default function ReturnSettlementBar({ value, restock, onRestockChange }) {
  return (
    <div className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة المرتجع (تقدير)</p>
        <p className="num font-heading text-[15px] font-bold text-rose-600">{fmtMoney(value)}</p>
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-[12px] font-semibold text-foreground/80">
        <input type="checkbox" checked={restock} onChange={(e) => onRestockChange(e.target.checked)} className="h-4 w-4 accent-[#F97316]" />
        إرجاع القطع للرف (المخزون)
      </label>

      <p className="max-w-[230px] text-center text-[11px] text-muted-foreground">يُرد المبلغ بنفس طريقة الدفع الأصلية للفاتورة</p>

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">المستحق للعميل</p>
        <p className="num font-heading text-lg font-extrabold text-emerald-600">{fmtMoney(value)}</p>
      </div>
    </div>
  );
}
