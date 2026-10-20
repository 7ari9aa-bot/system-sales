import { ArrowLeftRight } from "lucide-react";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// ملخص الحساب أسفل جدول البدائل: قيمة القطع المستبدلة، قيمة البدائل، ثم الفرق المطلوب أو المستحق.
export default function ExchangeSettlementBar({ exchangedValue, newValue, difference }) {
  const customerPays = difference > 0;
  const even = difference === 0;

  return (
    <div className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-center gap-x-6 gap-y-1 rounded-lg border border-border bg-card px-3 py-1.5">
      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة القطع المستبدلة</p>
        <p className="num font-heading text-[15px] font-bold text-rose-600">{fmtMoney(exchangedValue)}</p>
      </div>

      <ArrowLeftRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />

      <div className="text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة القطع البديلة</p>
        <p className="num font-heading text-[15px] font-bold text-violet-700">{fmtMoney(newValue)}</p>
      </div>

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">{even ? "تسوية متساوية" : customerPays ? "المطلوب من العميل" : "المستحق للعميل"}</p>
        <p
          className={cn(
            "num font-heading text-lg font-extrabold",
            even ? "text-muted-foreground" : customerPays ? "text-amber-600" : "text-emerald-600",
          )}
        >
          {fmtMoney(Math.abs(difference))}
        </p>
      </div>
    </div>
  );
}