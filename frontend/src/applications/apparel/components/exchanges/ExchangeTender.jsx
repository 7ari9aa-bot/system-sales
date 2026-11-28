import { Button } from "@/applications/apparel/components/ui/button";
import { Input } from "@/applications/apparel/components/ui/input";
import { changeDue, remainingToPay } from "@/applications/apparel/api/tenderPlan";
import { fmtMoney } from "@/applications/apparel/lib/format";

const METHOD_LABEL = { cash: "نقدي", card: "بطاقة", transfer: "تحويل", wallet: "محفظة" };
const label = (m) => METHOD_LABEL[m] ?? m;

/**
 * تحصيل فرق الاستبدال.
 *
 * A replacement that costs more is a sale of the difference: the customer hands over money now,
 * with the same tender rules as any sale on this till (the methods it accepts, a reference where
 * the shop demands one, split across methods when the profile allows more than one). Nothing here
 * touches the server; it only builds the lines the exchange request will carry.
 */
export default function ExchangeTender({ rules, due, lines, onChange }) {
  const left = remainingToPay(due, lines);
  const change = changeDue(lines);
  const unused = (rules?.methods ?? []).filter((m) => !lines.some((l) => l.method === m));
  const patch = (i, next) => onChange(lines.map((l, j) => (j === i ? { ...l, ...next } : l)));

  return (
    <div className="w-full space-y-2 rounded-lg border border-amber-300 bg-amber-50/60 p-2" aria-label="تحصيل فرق الاستبدال">
      <p className="text-[11px] font-bold text-amber-900">
        المطلوب تحصيله من العميل: <span className="num">{fmtMoney(Number(due))}</span>
      </p>

      {lines.map((l, i) => (
        <div key={`${l.method}-${i}`} className="space-y-1 rounded-md border border-amber-200 bg-white p-2">
          <div className="flex items-center gap-2">
            <span className="w-14 text-[12px] font-semibold">{label(l.method)}</span>
            <Input
              dir="ltr"
              inputMode="decimal"
              className="num h-8 flex-1"
              value={l.amount}
              aria-label={`مبلغ ${label(l.method)}`}
              onChange={(e) => patch(i, { amount: e.target.value })}
            />
            {lines.length > 1 ? (
              <Button
                type="button"
                variant="ghost"
                className="h-8 px-2"
                aria-label="حذف"
                onClick={() => onChange(lines.filter((_, j) => j !== i))}
              >
                ×
              </Button>
            ) : null}
          </div>
          {l.method === "cash" ? (
            <Input
              dir="ltr"
              inputMode="decimal"
              className="num h-8"
              placeholder="المبلغ المستلم (اختياري)"
              value={l.tendered}
              aria-label="المبلغ المستلم"
              onChange={(e) => patch(i, { tendered: e.target.value })}
            />
          ) : null}
          {(rules?.reference_required ?? []).includes(l.method) ? (
            <Input
              dir="ltr"
              className="h-8"
              placeholder="رقم المرجع"
              value={l.reference}
              aria-label="رقم المرجع"
              onChange={(e) => patch(i, { reference: e.target.value })}
            />
          ) : null}
        </div>
      ))}

      {unused.length ? (
        <div className="flex flex-wrap gap-2">
          {unused.map((m) => (
            <Button
              key={m}
              type="button"
              variant="outline"
              className="h-7 px-2 text-[11px]"
              onClick={() => onChange([...lines, { method: m, amount: left === "0.00" ? "" : left, tendered: "", reference: "" }])}
            >
              + {label(m)}
            </Button>
          ))}
        </div>
      ) : null}

      <div className="num flex items-center justify-between text-[11px] text-amber-900">
        <span>المتبقي</span>
        <span className="font-bold">{left}</span>
      </div>
      {Number(change) > 0 ? (
        <div className="num flex items-center justify-between text-[11px] text-emerald-700">
          <span>الباقي للعميل</span>
          <span className="font-bold">{change}</span>
        </div>
      ) : null}
    </div>
  );
}
