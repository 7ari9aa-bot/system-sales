import { History, Play, Trash2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { fmtDateTime, fmtMoney } from "@/cashier/lib/format";

// قائمة عمليات الاستبدال المعلقة لاستكمالها أو حذفها.
export default function HeldExchangesDialog({ open, onOpenChange, held, onResume, onDelete }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">عمليات الاستبدال المعلقة</DialogTitle>
          <DialogDescription>استكمل أي عملية معلقة من حيث توقفت، مع بقاء الفاتورة والبنود كما هي.</DialogDescription>
        </DialogHeader>

        {held.length === 0 ? (
          <EmptyState
            icon={History}
            title="لا توجد عمليات معلقة"
            description="عند تعليق أي عملية استبدال ستظهر هنا للاستكمال."
            compact
          />
        ) : (
          <ul className="max-h-[55vh] space-y-2 overflow-y-auto scroll-slim">
            {held.map((h) => (
              <li
                key={h.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-muted/40"
              >
                <div className="min-w-0">
                  <p className="num text-sm font-bold">{h.number}</p>
                  <p className="num text-[11px] text-muted-foreground">
                    {h.invoice ? `فاتورة ${h.invoice.number}` : "بدون فاتورة"} • {h.customer ?? "عميل نقدي"} • {fmtDateTime(h.heldAt)}
                  </p>
                  {h.note && <p className="mt-0.5 text-[11px] text-amber-700">{h.note}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="num text-xs font-semibold text-muted-foreground">
                    مستبدل {fmtMoney(h.returnedValue ?? 0)} • بدائل {fmtMoney(h.newValue ?? 0)}
                  </span>
                  <Button size="sm" className="h-8 gap-1.5" onClick={() => onResume(h)}>
                    <Play className="h-3.5 w-3.5" />
                    استكمال
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8 text-rose-600 hover:bg-rose-50"
                    onClick={() => onDelete(h.id)}
                    aria-label="حذف العملية المعلقة"
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