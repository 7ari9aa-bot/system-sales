import { useEffect, useRef, useState } from "react";
import { Minus, Plus, Trash2, TriangleAlert } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { fmtInt, fmtNumber } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// عدد الصفوف الفاضية الجاهزة في بداية الفاتورة.
const MIN_ROWS = 4;
// رأس الجدول وصف الإجماليات: نفس الخلفية الداكنة ونفس ارتفاعات التصميم.
const HCELL = "border border-slate-700 bg-slate-800 px-2 py-1.5 text-[12px] text-slate-50";
const CELL = "border border-border px-2 py-0.5";
// إخفاء أسهم حقول الأرقام: الخانات مخصصة لرقم صغير فقط.
const NO_SPINNER = "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";
// أزرار الكمية: هادئة حتى لا تنافس خانة الكتابة المباشرة.
const QTY_BTN = "h-5 w-5 shrink-0 text-muted-foreground hover:bg-accent hover:text-primary";

// خانة الكمية: الكتابة المباشرة هي الأساس، والأزرار مساعدة سريعة.
function QtyCell({ line, onQty, onQtyStep, onActivate, overStock }) {
  return (
    <div className="flex items-center justify-center gap-0.5">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={QTY_BTN}
        onClick={() => onQtyStep(line.lineId, -1)}
        aria-label={`تقليل كمية ${line.name}`}
      >
        <Minus className="h-3 w-3" />
      </Button>
      <input
        type="number"
        min={1}
        value={line.qty}
        onFocus={() => onActivate(line.lineId)}
        onChange={(e) => onQty(line.lineId, e.target.value)}
        className={cn(
          "num h-6 w-8 rounded-md border border-input bg-background text-center text-[13px] font-bold outline-none focus:border-ring focus:ring-1 focus:ring-ring",
          NO_SPINNER,
        )}
        aria-label={`كمية ${line.name}`}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={QTY_BTN}
        onClick={() => onQtyStep(line.lineId, 1)}
        aria-label={`زيادة كمية ${line.name}`}
      >
        <Plus className="h-3 w-3" />
      </Button>
      {overStock && <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" aria-label="الكمية أكبر من المتاح" />}
    </div>
  );
}

// جدول أصناف الفاتورة بمقاسات التصميم (رأس داكن، صفوف متبادلة، صف إجماليات في نهاية الجدول)
// والجدول يملأ المساحة المتاحة بصفوف فاضية إضافية تلقائياً.
export default function PosInvoiceTable({
  lines,
  totals,
  activeLineId,
  onActivate,
  onQty,
  onQtyStep,
  onDiscount,
  onRemove,
  maxDiscount = 100,
  barcode = "",
  onBarcodeChange,
  onBarcodeSubmit,
  children,
}) {
  const scrollRef = useRef(null);
  const cardRef = useRef(null);
  const entryRef = useRef(null);
  const extraRef = useRef(0);
  const [extraRows, setExtraRows] = useState(0);
  const rowCount = Math.max(MIN_ROWS, lines.length + 1) + extraRows;
  const rows = Array.from({ length: rowCount }, (_, index) => lines[index] ?? null);
  const discountTotal = (totals?.linesDiscount ?? 0) + (totals?.invoiceDiscount ?? 0);

  // أي صنف جديد = نزول تلقائي لآخر صف.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  // خانة الباركود ترجع لها التركيز تلقائياً بعد إضافة أو حذف صنف.
  useEffect(() => {
    entryRef.current?.focus();
  }, [lines.length]);

  // استغلال المساحة الفاضية أسفل الجدول: صفوف فاضية إضافية بعدد ما يتسع لها المكان.
  useEffect(() => {
    const container = scrollRef.current;
    const card = cardRef.current;
    if (!container || !card) return;

    function measure() {
      const rowHeight = card.querySelector("tbody tr")?.getBoundingClientRect().height || 33;
      const free = container.clientHeight - card.clientHeight;
      const next = Math.max(0, Math.floor((free + extraRef.current * rowHeight) / rowHeight));
      if (next !== extraRef.current) {
        extraRef.current = next;
        setExtraRows(next);
      }
    }

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    observer.observe(card);
    return () => observer.disconnect();
  }, [lines.length]);

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto scroll-slim">
      <div ref={cardRef} className="overflow-hidden rounded-lg border border-border bg-card">
        {/* شريط عنوان الجدول: نفس تنسيق جدول الاستبدال (عنوان + ملخص مختصر) */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-2.5 py-1.5">
          <p className="font-heading text-[13px] font-bold">أصناف الفاتورة</p>
          <p className="num text-[11px] text-muted-foreground">
            {lines.length === 0
              ? "امسح الباركود أو اكتبه في خانة الباركود لإضافة أول صنف"
              : `${fmtInt(lines.length)} صنف • ${fmtInt(totals?.pieces ?? 0)} قطعة`}
          </p>
        </div>

        <table className="w-full table-fixed border-collapse text-[13px]">
          <colgroup>
            {/* الرقم والإجمالي بعرض ثابت حتى لا يُقصّا أبدًا؛ اسم المنتج يأخذ المساحة المتبقية فيتقلص ويتوسع مع فتح/طي القائمة الجانبية */}
            <col className="w-[40px]" />
            <col className="w-[11%]" />
            <col />
            <col className="w-[6%]" />
            <col className="w-[7%]" />
            <col className="w-[11%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[112px]" />
            <col className="w-[44px]" />
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
              <th className={cn(HCELL, "text-center")}>خصم %</th>
              <th className={cn(HCELL, "text-center")}>الإجمالي</th>
              <th className={cn(HCELL, "text-center")}>حذف</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((line, index) => {
              if (!line) {
                // صف الإدخال: أول صف فاضي بعد آخر صنف يحمل خانة كتابة الباركود يدوياً أو بالمسح.
                const isEntryRow = index === lines.length;
                return (
                  <tr key={`empty-${index}`} className={cn("h-8", index % 2 === 1 ? "bg-muted/20" : "bg-card")}>
                    <td className={cn(CELL, "num text-center text-xs text-muted-foreground/70")}>{index + 1}</td>
                    <td className={cn(CELL, "p-0.5")}>
                      {isEntryRow ? (
                        <input
                          ref={entryRef}
                          value={barcode}
                          onChange={(e) => onBarcodeChange(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              onBarcodeSubmit();
                            }
                          }}
                          placeholder="امسح أو اكتب الباركود"
                          autoComplete="off"
                          className="num h-6 w-full rounded-md border border-input bg-background px-1 text-center text-[12px] font-semibold outline-none focus:ring-1 focus:ring-ring"
                          aria-label="باركود المنتج"
                        />
                      ) : null}
                    </td>
                    <td className={cn(CELL, "truncate text-xs text-muted-foreground/70")} />
                    <td className={CELL} />
                    <td className={CELL} />
                    <td className={CELL} />
                    <td className={CELL} />
                    <td className={CELL} />
                    <td className={CELL} />
                    <td className={CELL} />
                  </tr>
                );
              }

              const overStock = line.qty > line.stock;
              const active = line.lineId === activeLineId;
              const lineTotal = line.price * line.qty - line.discount;

              return (
                <tr
                  key={line.lineId}
                  onClick={() => onActivate(line.lineId)}
                  className={cn(
                    "h-8 transition-colors",
                    overStock ? "bg-amber-50" : active ? "bg-accent/70" : index % 2 === 1 ? "bg-muted/20" : "bg-card",
                    !overStock && !active && "hover:bg-accent/25",
                  )}
                >
                  {/* الصف المحدد: علامة جانبية بلون التمييز + رقم الصف مميز */}
                  <td
                    className={cn(
                      CELL,
                      "num text-center text-xs",
                      active ? "border-s-2 border-s-primary bg-primary/5 font-bold text-primary" : "text-muted-foreground",
                    )}
                  >
                    {index + 1}
                  </td>
                  <td className={cn(CELL, "num truncate text-center text-[12px] text-muted-foreground")} title={line.barcode || line.code}>
                    {line.barcode || line.code}
                  </td>
                  <td className={cn(CELL, "truncate", active ? "font-semibold text-foreground" : "font-medium")} title={line.name}>
                    {line.name}
                  </td>
                  <td className={cn(CELL, "text-center font-semibold")}>{line.size}</td>
                  <td className={cn(CELL, "overflow-hidden")}>
                    <ColorSwatch color={line.color} hex={line.hex} />
                  </td>
                  <td className={CELL}>
                    <QtyCell line={line} onQty={onQty} onQtyStep={onQtyStep} onActivate={onActivate} overStock={overStock} />
                  </td>
                  <td className={cn(CELL, "num text-center")}>{line.price.toFixed(2)}</td>
                  <td className={cn(CELL, line.discount > 0 && "bg-amber-50")}>
                    <div
                      className="flex items-center justify-center gap-0.5"
                      title={line.discount > 0 ? `قيمة الخصم على الصنف ${line.discount.toFixed(2)} ج.م` : "نسبة الخصم على الصنف"}
                    >
                      <input
                        type="number"
                        min={0}
                        max={maxDiscount}
                        value={line.discountPct}
                        onFocus={() => onActivate(line.lineId)}
                        onChange={(e) => onDiscount(line.lineId, e.target.value)}
                        className={cn(
                          "num h-6 w-9 rounded-md border border-input bg-background text-center outline-none focus:ring-1 focus:ring-ring",
                          NO_SPINNER,
                        )}
                        aria-label={`نسبة الخصم على ${line.name}`}
                      />
                      <span className="text-[11px] text-muted-foreground">%</span>
                    </div>
                  </td>
                  <td className={cn(CELL, "num text-center font-bold")}>{lineTotal.toFixed(2)}</td>
                  <td className={cn(CELL, "text-center")}>
                    {/* مربع الحذف يظهر في صفوف المنتجات المضافة فقط */}
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="h-6 w-6 border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(line);
                      }}
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
                الإجمالي الكامل
              </td>
              <td className={cn(HCELL, "num text-center")}>{fmtInt(totals?.pieces ?? 0)}</td>
              <td className={HCELL} />
              <td className={cn(HCELL, "num text-center")}>{discountTotal > 0 ? "-" : ""}{fmtNumber(discountTotal)}</td>
              <td className={cn(HCELL, "num text-center")}>{fmtNumber(totals?.total ?? 0)}</td>
              <td className={HCELL} />
            </tr>
          </tfoot>
        </table>

        {children}
      </div>
    </div>
  );
}