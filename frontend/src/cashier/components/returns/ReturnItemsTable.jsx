import { Trash2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import QtyStepper from "@/cashier/components/exchanges/QtyStepper";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const HCELL = "border border-slate-700 bg-slate-800 px-2 py-1.5 text-[12px] text-slate-50";
const CELL = "border border-border px-2 py-0.5";
const MIN_ROWS = 3;

// جدول أصناف المرتجع: القطع المنقولة من الفاتورة الأصلية مع تعديل الكمية أو حذف البند.
export default function ReturnItemsTable({ lines, totals, onQty, onQtyStep, onRemove, minRows = MIN_ROWS }) {
  const rows = Array.from({ length: Math.max(minRows, lines.length) }, (_, index) => lines[index] ?? null);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-2.5 py-1.5">
        <p className="font-heading text-[13px] font-bold">أصناف المرتجع</p>
        <p className="text-[11px] text-muted-foreground">
          {lines.length > 0 ? `القطع المنقولة من الفاتورة: ${fmtInt(totals.pieces)}` : "انقل القطع من جدول الفاتورة بزر الإرجاع"}
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
              <th className={cn(HCELL, "text-center")}>حذف</th>
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

              return (
                <tr key={line.key} className={cn("h-8 transition-colors", index % 2 === 1 ? "bg-muted/20" : "bg-card", "hover:bg-accent/25")}>
                  <td className={cn(CELL, "num text-center text-xs text-muted-foreground")}>{index + 1}</td>
                  <td className={cn(CELL, "num truncate text-center text-[12px] text-muted-foreground")}>{line.barcode}</td>
                  <td className={cn(CELL, "truncate font-medium")} title={line.name}>
                    {line.name}
                  </td>
                  <td className={cn(CELL, "text-center font-semibold")}>{line.size}</td>
                  <td className={cn(CELL, "overflow-hidden")}>
                    <ColorSwatch color={line.color} hex={line.hex} />
                  </td>
                  <td className={CELL}>
                    <QtyStepper
                      value={line.returnQty}
                      max={line.maxQty}
                      label={line.name}
                      onChange={(value) => onQty(line.key, value)}
                      onStep={(delta) => onQtyStep(line.key, delta)}
                    />
                  </td>
                  <td className={cn(CELL, "num text-center")}>{fmtMoney(line.unitNet)}</td>
                  <td className={cn(CELL, "num text-center font-bold text-rose-600")}>{fmtMoney(line.unitNet * line.returnQty)}</td>
                  <td className={cn(CELL, "text-center")}>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="h-6 w-6 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => onRemove(line)}
                      aria-label={`حذف ${line.name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>

          <tfoot>
            <tr className="font-bold">
              <td colSpan={5} className={cn(HCELL, "text-start")}>
                إجمالي الأصناف المرتجعة
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