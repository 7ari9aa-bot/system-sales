import { ArrowLeftRight } from "lucide-react";
import { fmtMoney } from "@/applications/apparel/lib/format";
import { cn } from "@/applications/apparel/lib/utils";
import ExchangeTender from "@/applications/apparel/components/exchanges/ExchangeTender";
import { CONDITIONS, conditionEffect } from "@/applications/apparel/api/returnPlan";
import { settlementPrompt } from "@/applications/apparel/api/exchangePlan";

const REFUND_METHODS = [
  ["", "وسيلة الدفع الأصلية"],
  ["cash", "نقدي من الدرج"],
  ["card", "بطاقة (على الماكينة)"],
  ["wallet", "محفظة"],
  ["bank_transfer", "تحويل بنكي"],
];

// ملخص الحساب: قيمة المرتجع (تقدير بنفس معادلة الخادم)، إجمالي البدائل (من الخادم)، ثم الفرق.
// الفرق فلوس بتتحرك فعلًا: البديل الأغلى بيتحصّل فرقه، والأرخص بيترد فرقه على وسيلة الدفع الأصلية.
export default function ExchangeSettlementBar({
  lines = [],
  onCondition = null,
  exchangedValue,
  newValue,
  difference,
  loading = false,
  error = null,
  restock,
  onRestockChange,
  reasons,
  reason,
  onReasonChange,
  rules = null,
  tenderLines = [],
  onTenderChange,
  refundMethod = "",
  onRefundMethodChange,
}) {
  const back = lines.filter((l) => l.returnQty > 0);
  const customerPays = difference > 0;
  const even = difference === 0;
  const recording = Boolean(rules?.take_payments);
  const kind = even ? "even" : customerPays ? "pay" : "refund";

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

      {back.length ? (
        <div className="w-full border-t border-border/60 pt-1" data-testid="exchange-conditions">
          <p className="text-center text-[11px] font-semibold text-foreground/70">حالة القطع الراجعة (بتحدد أثرها على المخزون)</p>
          <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
            {back.map((l) => (
              <label key={l.variantId} className="flex items-center gap-1 text-[11px]">
                <span className="max-w-[110px] truncate" title={l.name}>{l.name}</span>
                <select
                  className="h-7 rounded-md border border-border bg-card px-1 text-[11px]"
                  value={l.condition ?? "sellable"}
                  title={conditionEffect(l.condition)}
                  aria-label={`حالة القطعة ${l.name}`}
                  onChange={(e) => onCondition?.(l.variantId, e.target.value)}
                >
                  {CONDITIONS.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-lg bg-muted/50 px-4 py-1 text-center">
        <p className="text-[12px] font-semibold text-foreground/70">{even ? "لا فرق في القيمة" : customerPays ? "المطلوب تحصيله من العميل" : "المطلوب ردّه للعميل"}</p>
        <p className={cn("num font-heading text-lg font-extrabold", even ? "text-muted-foreground" : customerPays ? "text-amber-600" : "text-emerald-600")}>
          {loading ? "…" : fmtMoney(Math.abs(difference))}
        </p>
      </div>

      {/* التحصيل: بنفس قواعد البيع على الكاشير ده (وسيلة، مرجع، تقسيم لو البروفايل بيسمح) */}
      {recording && customerPays && !loading && onTenderChange ? (
        <ExchangeTender rules={rules} due={difference} lines={tenderLines} onChange={onTenderChange} />
      ) : null}

      {/* الرد: وسيلة الدفع اللي بيرجع عليها الفرق */}
      {recording && !customerPays && !even && !loading && onRefundMethodChange ? (
        <label className="flex items-center gap-2 text-[11px] font-semibold text-foreground/80">
          الفرق يرجع على
          <select
            className="h-8 rounded-md border border-border bg-white px-2 text-[11px]"
            value={refundMethod}
            onChange={(e) => onRefundMethodChange(e.target.value)}
            aria-label="وسيلة رد الفرق"
          >
            {REFUND_METHODS.map(([value, text]) => (
              <option key={value || "original"} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <p className="w-full text-center text-[11px] text-muted-foreground">
        {error ? (
          <span role="alert" className="font-semibold text-rose-600">
            {error}
          </span>
        ) : (
          <>
            {settlementPrompt(kind, difference, { takePayments: recording })}
            {recording && !even ? " · البدائل تُسعَّر بالسعر الحالي بدون خصم" : ""}
          </>
        )}
      </p>
    </div>
  );
}
