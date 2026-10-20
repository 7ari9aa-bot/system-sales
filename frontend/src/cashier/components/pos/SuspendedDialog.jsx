import { History, Play, Trash2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { fmtMoney, fmtTime } from "@/cashier/lib/format";

// قائمة الفواتير المعلقة لاستعادتها أو حذفها.
export default function SuspendedDialog({ open, onOpenChange, suspended, onResume, onDelete }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">الفواتير المعلقة</DialogTitle>
          <DialogDescription>استعد أي فاتورة معلقة لمتابعة البيع من حيث توقفت.</DialogDescription>
        </DialogHeader>

        {suspended.length === 0 ? (
          <EmptyState icon={History} title="لا توجد فواتير معلقة" description="عند تعليق أي فاتورة ستظهر هنا للاستعادة." compact />
        ) : (
          <ul className="max-h-[55vh] space-y-2 overflow-y-auto scroll-slim">
            {suspended.map((s) => {
              const total = s.items.reduce((sum, it) => sum + it.total, 0);
              const pieces = s.items.reduce((sum, it) => sum + it.qty, 0);
              return (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-muted/40">
                  <div className="min-w-0">
                    <p className="num text-sm font-bold">{s.number}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {s.customerName} • {pieces} قطعة • {fmtTime(s.heldAt)} • {s.cashier}
                    </p>
                    {s.note && <p className="mt-0.5 text-[11px] text-amber-700">{s.note}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="num text-sm font-semibold">{fmtMoney(total)}</span>
                    <Button size="sm" className="h-8 gap-1.5" onClick={() => onResume(s)}>
                      <Play className="h-3.5 w-3.5" />
                      استعادة
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 text-rose-600 hover:bg-rose-50"
                      onClick={() => onDelete(s.id)}
                      aria-label="حذف الفاتورة المعلقة"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}