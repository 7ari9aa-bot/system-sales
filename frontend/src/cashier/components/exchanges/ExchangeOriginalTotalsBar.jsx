import { ArrowDown, ArrowLeft } from "lucide-react";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// إجمالي قيمة القطع المستبدلة أسفل جدول الفاتورة الأصلية — بنفس شكل شريط التسوية أسفل جدول البدائل.
export default function ExchangeOriginalTotalsBar({ totals }) {
  return (
    <div className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-center gap-x-6 gap-y-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">إجمالي قيمة القطع المستبدلة</p>
        <p className="num font-heading text-[15px] font-bold text-rose-600">{fmtMoney(totals.value)}</p>
      </div>

      <ArrowLeft className="hidden h-4 w-4 text-muted-foreground 2xl:block" aria-hidden="true" />
      <ArrowDown className="h-4 w-4 text-muted-foreground 2xl:hidden" aria-hidden="true" />

      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">عدد القطع المستبدلة</p>
        <p className="num font-heading text-[15px] font-bold text-primary">{fmtInt(totals.pieces)} قطعة</p>
      </div>
    </div>
  );
}