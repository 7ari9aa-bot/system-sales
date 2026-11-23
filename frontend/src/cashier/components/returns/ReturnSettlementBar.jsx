import { fmtMoney } from "@/cashier/lib/format";
import { conditionSplit } from "@/cashier/api/returnPlan";
import ReturnReasonSelect from "@/cashier/components/returns/ReturnReasonSelect";

// ملخص أسفل جدول المرتجع. الخادم هو اللي بيرد المبلغ على وسائل الدفع الأصلية للفاتورة،
// والقيمة المعروضة تقدير بنفس معادلة الخادم؛ النتيجة النهائية (المردود فعليًا واللي ما اتحصّلش)
// بتيجي منه بعد الاعتماد وتظهر في رسالة التأكيد والإيصال.
export default function ReturnSettlementBar({ value, restock, onRestockChange, reasons, reason, onReasonChange, lines = [], takePayments = null }) {
  const split = conditionSplit(lines);
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

      <ReturnReasonSelect reasons={reasons} value={reason} onChange={onReasonChange} />

      {split.length ? (
        <div className="text-center" data-testid="condition-split">
          <p className="text-[11px] font-semibold text-foreground/70">حالة القطع الراجعة</p>
          <p className="text-[11px] text-muted-foreground">
            {split.map((c) => `${c.units} ${c.label}`).join(" · ")}
          </p>
        </div>
      ) : null}

      <p className="max-w-[250px] text-center text-[11px] text-muted-foreground">
        {takePayments === false
          ? "الكاشير مش بيسجّل مدفوعات: المبلغ يتسجّل على الفاتورة فقط"
          : "الخادم يرد المبلغ على وسائل الدفع الأصلية: النقدي يخرج من درج الوردية، والبطاقة أو المحفظة تتعكس على الماكينة ويُسجَّل رقم المرجع"}
      </p>

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">قيمة المرتجع</p>
        <p className="num font-heading text-lg font-extrabold text-emerald-600">{fmtMoney(value)}</p>
      </div>
    </div>
  );
}
