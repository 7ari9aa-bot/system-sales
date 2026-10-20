import { Trash2, TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import QtyStepper from "@/cashier/components/exchanges/QtyStepper";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const HCELL = "border border-slate-700 bg-slate-800 px-2 py-1.5 text-[12px] text-slate-50";
const CELL = "border border-border px-2 py-0.5";
const MIN_ROWS = 10;

// جدول المنتجات البديلة: خانة المسح/البحث داخل الصف الأخير، مع نتائج مطابقة أسفل الجدول.
export default function ExchangeNewItemsTable({
  lines,
  term,
  onTermChange,
  onSubmit,
  onQty,
  onQtyStep,
  onRemove,
  matches,
  onPick,
  error,
  totals,
  movedPieces = 0,
  minRows = MIN_ROWS,
}) {
  const rows = Array.from({ length: Math.max(minRows, lines.length + 1) }, (_, index) => lines[index] ?? null);
  const showMatches = term.trim().length > 0 && matches.length > 0;

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-2.5 py-1.5">
        <p className="font-heading text-[13px] font-bold">القطع البديلة</p>
        <p className="text-[11px] text-muted-foreground">
          {movedPieces > 0 ? `القطع المُحوَّلة من الفاتورة: ${fmtInt(movedPieces)}` : "امسح باركود القطعة الجديدة أو ابحث بالاسم"}
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
                const isEntryRow = index === lines.length;
                return (
                  <tr key={`empty-${index}`} className={cn("h-8", index % 2 === 1 ? "bg-muted/20" : "bg-card")}>
                    <td className={cn(CELL, "num text-center text-xs text-muted-foreground/70")}>{index + 1}</td>
                    <td className={cn(CELL, "p-0.5")} colSpan={isEntryRow ? 2 : 1}>
                      {isEntryRow ? (
                        <input
                          value={term}
                          onChange={(e) => onTermChange(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              onSubmit();
                            }
                          }}
                          placeholder="ابحث عن المنتج البديل بالاسم أو الباركود"
                          autoComplete="off"
                          className="num h-6 w-full rounded-md border border-input bg-background px-1 text-center text-[12px] font-semibold outline-none focus:ring-1 focus:ring-ring"
                          aria-label="بحث عن المنتج البديل"
                        />
                      ) : null}
                    </td>
                    {Array.from({ length: isEntryRow ? 6 : 7 }, (_, blank) => (
                      <td key={`blank-${blank}`} className={CELL} />
                    ))}
                  </tr>
                );
              }

              return (
                <tr key={line.lineId} className={cn("h-8 transition-colors", index % 2 === 1 ? "bg-muted/20" : "bg-card", "hover:bg-accent/25")}>
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
                      value={line.qty}
                      max={Math.max(line.stock, line.qty)}
                      label={line.name}
                      onChange={(value) => onQty(line.lineId, value)}
                      onStep={(delta) => onQtyStep(line.lineId, delta)}
                    />
                  </td>
                  <td className={cn(CELL, "num text-center")}>{fmtMoney(line.price)}</td>
                  <td className={cn(CELL, "num text-center font-bold")}>{fmtMoney(line.price * line.qty)}</td>
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
                إجمالي قيمة البدائل
              </td>
              <td className={cn(HCELL, "num text-center")}>{fmtInt(totals.pieces)}</td>
              <td className={HCELL} />
              <td className={cn(HCELL, "num text-center")}>{fmtMoney(totals.value)}</td>
              <td className={HCELL} />
            </tr>
          </tfoot>
        </table>
      </div>

      {(showMatches || error) && (
        <div className="border-t border-border bg-muted/30 px-2 py-1.5">
          {error && (
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-rose-600">
              <TriangleAlert className="h-3.5 w-3.5" />
              {error}
            </p>
          )}
          {showMatches && (
            <ul className="grid max-h-24 gap-1 overflow-y-auto scroll-slim sm:grid-cols-2">
              {matches.slice(0, 6).map((v) => (
                <li key={v.id}>
                  <button
                    type="button"
                    onClick={() => onPick(v)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-border px-2 py-1 text-start transition-colors hover:border-primary hover:bg-accent"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[12px] font-medium">{v.productName}</span>
                      <span className="num block text-[10px] text-muted-foreground">
                        {v.color} / {v.size} • متاح {v.stock}
                      </span>
                    </span>
                    <span className="num shrink-0 text-[11px] font-semibold text-primary">{fmtMoney(v.sellPrice)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}