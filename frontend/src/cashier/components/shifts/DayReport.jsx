import { Link } from "react-router-dom";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { useShiftSales } from "@/cashier/api/usePosSale";
import { totalsOf } from "@/cashier/api/salesLog";
import { fmtDateTime, fmtInt, fmtMoney, fmtMoneyOrDash } from "@/cashier/lib/format";

/** The day's figures from the shift row and its invoices. Pure, so it is tested without React. */
export function dayReportFigures(shift, sales = []) {
  // `sales === null` means the invoices are not available (still loading, or the request failed):
  // everything built from them is unknown, not zero.
  const available = Array.isArray(sales);
  const { total, pieces } = available ? totalsOf(sales) : { total: null, pieces: null };
  const opening = Number(shift?.openingCash ?? 0);
  const returns = Number(shift?.returnsTotal ?? 0);
  // Opening + invoices - returns, from the backend's own report. Nothing is counted at the drawer.
  const stored = shift?.closingBalance;
  const closing = stored != null ? Number(stored) : available ? opening + total - returns : null;
  return {
    available,
    invoices: available ? sales.length : null,
    pieces,
    total,
    opening,
    returns,
    closing,
    returnDocs: shift?.returnDocs ?? [],
    exchangeDocs: shift?.exchangeDocs ?? [],
    exchangeDifference: Number(shift?.exchangeDifference ?? 0),
    closed: shift?.status === "closed" || shift?.closedAt != null,
  };
}

function Row({ label, value, strong }) {
  return (
    <div className="flex items-center justify-between border-b border-border/70 py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`num ${strong ? "font-bold" : "font-medium"}`}>{value}</span>
    </div>
  );
}

function DocList({ title, docs, exchange = false }) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-muted-foreground">{title}</p>
      <div className="overflow-hidden rounded-xl border border-border">
        {docs.map((d) => (
          <div key={d.receipt_id} className="flex items-center justify-between border-b border-border/70 px-3 py-2.5 text-sm last:border-0">
            <span className="num font-bold text-[#d9600a]">{d.receipt_number}</span>
            <span className="num text-xs text-muted-foreground">{fmtDateTime(d.issued_at)}</span>
            <span className="num text-xs text-muted-foreground">{fmtInt(d.units)} قطعة</span>
            <span className="num font-bold">{exchange ? `${fmtMoney(Number(d.total))} ← ${fmtMoney(Number(d.new_total))}` : fmtMoney(Number(d.total))}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// تقرير اليوم: وقت الفتح والإغلاق، رصيد الدرج، عدد الفواتير وإجمالي المبيعات، وكل فاتورة تُفتح بالضغط عليها.
export default function DayReport({ open, onOpenChange, shift }) {
  const sales = useShiftSales(open ? shift?.id : "");
  if (!shift) return null;
  const rows = sales.isSuccess ? (sales.data ?? []) : null; // null: loading or failed, not "no invoices"
  const f = dayReportFigures(shift, rows);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تقرير اليوم</DialogTitle>
          <DialogDescription>
            {shift.employee} • فتح {fmtDateTime(shift.date)}
            {shift.closedAt ? ` • إغلاق ${fmtDateTime(shift.closedAt)}` : " • اليوم ما زال مفتوحًا"}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-xl border border-border p-3">
          <Row label="رصيد بداية اليوم" value={fmtMoney(f.opening)} />
          <Row label="عدد الفواتير" value={f.invoices == null ? "—" : fmtInt(f.invoices)} />
          <Row label="عدد القطع المباعة" value={f.pieces == null ? "—" : fmtInt(f.pieces)} />
          <Row label="إجمالي المبيعات" value={fmtMoneyOrDash(f.total)} strong />
          <Row label={`المرتجعات (${fmtInt(f.returnDocs.length)})`} value={`−${fmtMoney(f.returns)}`} />
          <Row label="رصيد نهاية اليوم" value={fmtMoneyOrDash(f.closing)} strong />
        </div>

        {f.returnDocs.length > 0 ? <DocList title="فواتير الإرجاع" docs={f.returnDocs} /> : null}
        {f.exchangeDocs.length > 0 ? (
          <DocList title={`فواتير الاستبدال • فرق القيمة ${fmtMoney(f.exchangeDifference)}`} docs={f.exchangeDocs} exchange />
        ) : null}

        <div>
          <p className="mb-2 text-xs font-semibold text-muted-foreground">فواتير اليوم (اضغط على أي فاتورة لتفاصيلها)</p>
          <div className="max-h-72 overflow-y-auto rounded-xl border border-border">
            {sales.isLoading ? (
              <p role="status" className="p-4 text-center text-sm text-muted-foreground">جارٍ تحميل الفواتير…</p>
            ) : sales.isError ? (
              <p role="alert" className="p-4 text-center text-sm text-rose-600">تعذّر تحميل الفواتير. أعد فتح التقرير.</p>
            ) : rows && rows.length === 0 ? (
              <p className="p-4 text-center text-sm text-muted-foreground">لا توجد فواتير في هذا اليوم.</p>
            ) : (
              (rows ?? []).map((inv) => (
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
