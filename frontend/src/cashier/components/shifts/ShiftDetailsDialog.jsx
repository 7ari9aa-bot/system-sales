import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";

function Row({ label, value, tone }) {
  return (
    <div className="flex items-center justify-between border-b border-border/70 py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className={`num font-medium ${tone ?? ""}`}>{value}</span>
    </div>
  );
}

// تفاصيل وردية: الحركة النقدية، طرق الدفع، والمطابقة عند الإغلاق.
export default function ShiftDetailsDialog({ open, onOpenChange, shift }) {
  if (!shift) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تفاصيل الوردية {shift.number}</DialogTitle>
          <DialogDescription>
            {shift.employee} • فتح {fmtDateTime(shift.date)}
            {shift.closedAt ? ` • إغلاق ${fmtDateTime(shift.closedAt)}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <StatusBadge kind="shift" value={shift.status} />
          <span className="num text-xs text-muted-foreground">
            {fmtInt(shift.invoices)} فاتورة • {fmtInt(shift.pieces)} قطعة
          </span>
        </div>

        <div className="rounded-xl border border-border p-3">
          <Row label="رصيد بداية اليوم" value={fmtMoney(shift.openingCash)} />
          <Row label="إجمالي الفواتير" value={fmtMoney(shift.salesTotal)} />
          <Row label="إجمالي المرتجعات" value={`−${fmtMoney(shift.returnsTotal)}`} tone="text-rose-600" />
          <Row label="رصيد نهاية اليوم" value={fmtMoney(shift.closingBalance)} tone="font-bold" />
        </div>

        {shift.note && <p className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">{shift.note}</p>}
      </DialogContent>
    </Dialog>
  );
}