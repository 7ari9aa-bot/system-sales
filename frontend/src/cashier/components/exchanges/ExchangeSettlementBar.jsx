import { ArrowLeftRight } from "lucide-react";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// ملخص الحساب: قيمة المرتجع (تقدير بنفس معادلة الخادم)، إجمالي البدائل (من الخادم)، ثم الفرق.
// الفرق الموجب يدفعه العميل، والسالب يُرد له على طريقة الدفع الأصلية تلقائيًا.
export default function ExchangeSettlementBar({ exchangedValue, newValue, difference, loading = false, error = null, restock, onRestockChange }) {
  const customerPays = difference > 0;
  const even = difference === 0;

  return (
    <div className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-center gap-x-5 gap-y-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة القطع المرتجعة (تقدير)</p>
        <p className="num font-heading text-[15px] font-bold text-rose-600">{fmtMoney(exchangedValue)}</p>
      </div>

      <ArrowLeftRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />

      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">إجمالي القطع البديلة</p>
        <p className="num font-heading text-[15px] font-bold text-violet-700" aria-busy={loading}>
          {loading ? "…" : fmtMoney(newValue)}
        </p>
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-[12px] font-semibold text-foreground/80">
        <input type="checkbox" checked={restock} onChange={(e) => onRestockChange(e.target.checked)} className="h-4 w-4 accent-[#F97316]" />
        إرجاع القطع للرف (المخزون)
      </label>

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">{even ? "تسوية متساوية" : customerPays ? "المطلوب من العميل" : "المستحق للعميل"}</p>
        <p className={cn("num font-heading text-lg font-extrabold", even ? "text-muted-foreground" : customerPays ? "text-amber-600" : "text-emerald-600")}>
          {loading ? "…" : fmtMoney(Math.abs(difference))}
        </p>
      </div>

      <p className="w-full text-center text-[11px] text-muted-foreground">
        {error ? <span role="alert" className="font-semibold text-rose-600">{error}</span> : "البدائل تُسعَّر بالسعر الحالي بدون خصم، والفرق النهائي يحسبه الخادم"}
      </p>
    </div>
  );
}
