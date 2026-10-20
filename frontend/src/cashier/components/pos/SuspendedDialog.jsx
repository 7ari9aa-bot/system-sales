import { History, Play, Trash2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { fmtTime } from "@/cashier/lib/format";

// الفواتير المعلقة على هذه الوردية. لا يوجد سعر هنا عمداً: الخادم لا يحفظ أسعاراً ولا يحجز مخزوناً
// عند التعليق، فالسعر والمتاح يُحسبان من جديد وقت الاستعادة.
export default function SuspendedDialog({ open, onOpenChange, held = [], loading = false, error = null, busyId = null, onResume, onDelete }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">الفواتير المعلقة</DialogTitle>
          <DialogDescription>الأسعار والمتاح من المخزون تُحسب من جديد عند الاستعادة.</DialogDescription>
        </DialogHeader>

        {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>
        ) : held.length === 0 ? (
          <EmptyState icon={History} title="لا توجد فواتير معلقة" description="عند تعليق أي فاتورة ستظهر هنا للاستعادة." compact />
        ) : (
          <ul className="max-h-[55vh] space-y-2 overflow-y-auto scroll-slim">
            {held.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-muted/40">
                <div className="min-w-0">
                  <p className="text-sm font-bold">{h.label}</p>
                  <p className="num text-[11px] text-muted-foreground">
                    {h.pieces} قطعة • {fmtTime(h.createdAt)}
                  </p>
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{h.lines.map((l) => `${l.name} × ${l.qty}`).join("، ")}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" className="h-8 gap-1.5" disabled={busyId === h.id} onClick={() => onResume(h)}>
                    <Play className="h-3.5 w-3.5" />
                    استعادة
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 text-rose-600 hover:bg-rose-50"
                    disabled={busyId === h.id}
                    onClick={() => onDelete(h)}
                    aria-label={`حذف ${h.label}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
