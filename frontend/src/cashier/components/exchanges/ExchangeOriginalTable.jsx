import { ArrowLeftRight, X } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import QtyStepper from "@/cashier/components/exchanges/QtyStepper";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// رأس داكن وحدود موحّدة مع جدول المبيعات.
const HCELL = "border border-slate-700 bg-slate-800 px-2 py-1.5 text-[12px] text-slate-50";
const CELL = "border border-border px-2 py-0.5";
const MIN_ROWS = 10;

// جدول الفاتورة الأصلية: قراءة فقط بنفس أعمدة جدول المبيعات (بلا حذف أو تعديل على الكمية أو الخصم)،
// مع عمود «استبدال» لنقل القطع إلى جدول البدائل؛ ما لا يُنقل يبقى في الفاتورة.
export default function ExchangeOriginalTable({ invoice, lines, onStart, onQty, onQtyStep, onCancel, totals, minRows = MIN_ROWS }) {
  const rows = Array.from({ length: Math.max(minRows, lines.length) }, (_, index) => lines[index] ?? null);
  const movedLines = lines.filter((l) => l.moveQty > 0).length;

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-2.5 py-1.5">
        <p className="font-heading text-[13px] font-bold">
          الفاتورة الأصلية
          {invoice ? <span className="num ms-1.5 text-muted-foreground">{invoice.number}</span> : null}
        </p>
        <p className="text-[11px] text-muted-foreground">
          {invoice
            ? `للعرض فقط — اضغط زر الاستبدال لنقل القطعة (${fmtInt(movedLines)} بند مُحوَّل)`
            : "ابحث عن الفاتورة الأصلية بالأعلى لعرض أصنافها"}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-auto scroll-slim">
        <table className="w-full table-fixed border-collapse text-[13px]">
          <colgroup>
            <col className="w-[3%]" />
            <col className="w-[12%]" />
            <col className="w-[22%]" />
            <col className="w-[5%]" />
            <col className="w-[7%]" />
            <col className="w-[16%]" />
            <col className="w-[9%]" />
            <col className="w-[10%]" />
            <col className="w-[16%]" />
          </colgroup>

          <thead className="sticky top-0 z-10">
            <tr className="font-bold">
              <th className={cn(HCELL, "text-center")}>م</th>
              <th className={cn(HCELL, "text-center")}>الباركود</th>
              <th className={cn(HCELL, "text-start")}>اسم المنتج</th>
              <th className={cn(HCELL, "text-center")}>المقاس</th>
              <th className={cn(HCELL, "text-center")}>اللون</th>
              <th className={cn(HCELL, "text-center")}>الكمية</th>
              <th className={cn(HCELL, "text-center")}>السعر</th>
              <th className={cn(HCELL, "text-center")}>الإجمالي</th>
              <th className={cn(HCELL, "text-center")}>استبدال</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((line, index) => {
              if (!line) {
                return (
                  <tr key={`empty-${index}`} className={cn("h-8", index % 2 === 1 ? "bg-muted/20" : "bg-card")}>
                    <td className={cn(CELL, "num text-center text-xs text-muted-foreground/70")}>{index + 1}</td>
                    {Array.from({ length: 8 }, (_, blank) => (
                      <td key={`blank-${blank}`} className={CELL} />
                    ))}
                  </tr>
                );
              }

              const fullyMoved = line.moveQty > 0 && line.moveQty >= line.maxQty;

              return (
                <tr
                  key={line.key}
                  className={cn(
                    "h-8 transition-colors",
                    fullyMoved
                      ? "bg-muted/40 text-muted-foreground"
                      : line.moveQty > 0
                        ? "bg-accent/50"
                        : index % 2 === 1
                          ? "bg-muted/20"
                          : "bg-card",
                  )}
                >
                  <td className={cn(CELL, "num text-center text-xs text-muted-foreground")}>{index + 1}</td>
                  <td className={cn(CELL, "num truncate text-center text-[12px] text-muted-foreground")} title={line.barcode}>
                    {line.barcode}
                  </td>
                  <td className={cn(CELL, "truncate", fullyMoved ? "line-through" : "font-medium")} title={line.name}>
                    {line.name}
                  </td>
                  <td className={cn(CELL, "text-center font-semibold")}>{line.size}</td>
                  <td className={cn(CELL, "overflow-hidden")}>
                    <ColorSwatch color={line.color} hex={line.hex} />
                  </td>
                  <td className={cn(CELL, "num text-center")}>
                    {line.qty}
                    {line.alreadyExchanged > 0 && (
                      <span className="block text-[10px] text-rose-600" title="سبق استبداله">
                        سبق {line.alreadyExchanged}
                      </span>
                    )}
                  </td>
                  <td className={cn(CELL, "num text-center")}>
                    {fmtMoney(line.price)}
                    {line.discountPct ? <span className="block text-[10px] text-muted-foreground">خصم {line.discountPct}%</span> : null}
                  </td>
                  <td className={cn(CELL, "num text-center font-bold")}>{fmtMoney(line.total)}</td>
                  <td className={cn(CELL, "text-center")}>
                    {line.maxQty === 0 ? (
                      <span className="text-[10px] font-semibold text-muted-foreground">سبق استبداله</span>
                    ) : line.moveQty === 0 ? (
                      <div className="flex items-center justify-center gap-1">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="h-6 w-6 border-primary/40 text-primary hover:bg-accent hover:text-accent-foreground"
                          onClick={() => onStart(line.key)}
                          aria-label={`نقل ${line.name} إلى جدول البدائل`}
                        >
                          <ArrowLeftRight className="h-3.5 w-3.5" />
                        </Button>
                        <span className="num text-[10px] text-muted-foreground">متاح {line.maxQty}</span>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-0.5">
                        <div className="flex items-center gap-1">
                          <QtyStepper
                            value={line.moveQty}
                            max={line.maxQty}
                            label={line.name}
                            onChange={(value) => onQty(line.key, value)}
                            onStep={(delta) => onQtyStep(line.key, delta)}
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 text-muted-foreground hover:text-destructive"
                            onClick={() => onCancel(line.key)}
                            aria-label={`إلغاء نقل ${line.name}`}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                        <span className="num text-[10px] font-semibold text-primary">{fmtMoney(line.unitNet * line.moveQty)}</span>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>

          <tfoot>
            <tr className="font-bold">
              <td colSpan={5} className={cn(HCELL, "text-start")}>
                إجمالي قيمة القطع المستبدلة
              </td>
              <td className={cn(HCELL, "num text-center")}>{fmtInt(totals.pieces)}</td>
              <td className={HCELL} />
              <td className={cn(HCELL, "num text-center")}>{fmtMoney(totals.value)}</td>
              <td className={HCELL} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}