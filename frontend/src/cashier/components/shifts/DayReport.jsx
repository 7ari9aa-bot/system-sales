import { Link } from "react-router-dom";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { useShiftSales } from "@/cashier/api/usePosSale";
import { totalsOf } from "@/cashier/api/salesLog";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";

/** The day's figures from the shift row and its invoices. Pure, so it is tested without React. */
export function dayReportFigures(shift, sales = []) {
  const { total, pieces } = totalsOf(sales);
  const opening = Number(shift?.openingCash ?? 0);
  const counted = shift?.actual == null ? null : Number(shift.actual);
  return { invoices: sales.length, pieces, total, opening, counted, closed: shift?.status === "closed" || shift?.closedAt != null };
}

function Row({ label, value, strong }) {
  return (
    <div className="flex items-center justify-between border-b border-border/70 py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`num ${strong ? "font-bold" : "font-medium"}`}>{value}</span>
    </div>
  );
}

// تقرير اليوم: وقت الفتح والإغلاق، رصيد الدرج، عدد الفواتير وإجمالي المبيعات، وكل فاتورة تُفتح بالضغط عليها.
export default function DayReport({ open, onOpenChange, shift }) {
  const sales = useShiftSales(open ? shift?.id : "");
  if (!shift) return null;
  const rows = sales.data ?? [];
  const f = dayReportFigures(shift, rows);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تقرير اليوم</DialogTitle>
          <DialogDescription>
            {shift.employee} • فتح {fmtDateTime(shift.date)}
            {shift.closedAt ? ` • إغلاق ${fmtDateTime(shift.closedAt)}` : " • الوردية ما زالت مفتوحة"}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-xl border border-border p-3">
          <Row label="بدأ اليوم والدرج فيه" value={fmtMoney(f.opening)} />
          <Row label="عدد الفواتير" value={fmtInt(f.invoices)} />
          <Row label="عدد القطع المباعة" value={fmtInt(f.pieces)} />
          <Row label="إجمالي المبيعات" value={fmtMoney(f.total)} strong />
          {f.counted != null ? <Row label="انتهى اليوم والدرج فيه" value={fmtMoney(f.counted)} strong /> : null}
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">فواتير اليوم (اضغط على أي فاتورة لتفاصيلها)</p>
          <div className="max-h-72 overflow-y-auto rounded-xl border border-border">
            {sales.isLoading ? (
              <p role="status" className="p-4 text-center text-sm text-muted-foreground">جارٍ تحميل الفواتير…</p>
            ) : sales.isError ? (
              <p role="alert" className="p-4 text-center text-sm text-rose-600">تعذّر تحميل الفواتير. أعد فتح التقرير.</p>
            ) : rows.length === 0 ? (
              <p className="p-4 text-center text-sm text-muted-foreground">لا توجد فواتير في هذا اليوم.</p>
            ) : (
              rows.map((inv) => (
                <Link
                  key={inv.id}
                  to={`/cashier/sales/${inv.id}?shift=${encodeURIComponent(shift.id)}`}
                  className="flex items-center justify-between border-b border-border/70 px-3 py-2.5 text-sm last:border-0 hover:bg-muted/50"
                >
                  <span className="num font-bold text-[#d9600a]">{inv.number}</span>
                  <span className="num text-xs text-muted-foreground">{fmtDateTime(inv.date)}</span>
                  <span className="num text-xs text-muted-foreground">{fmtInt(inv.pieces)} قطعة</span>
                  <span className="num font-bold">{fmtMoney(inv.total)}</span>
                </Link>
              ))
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
