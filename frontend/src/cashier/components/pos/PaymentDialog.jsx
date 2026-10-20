import { useEffect, useMemo, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { settle } from "@/cashier/api/checkout";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// Every sale is cash for now (owner decision: no payment-method system until the market is clear).
// The backend still requires a tender, so we always send one cash tender. `total` is the backend quote.
export default function PaymentDialog({ open, onOpenChange, total, customerName, onConfirm, pending = false, error = null }) {
  const [paid, setPaid] = useState("");

  useEffect(() => {
    // Open with the exact total: the common one-tap sale.
    if (open) setPaid(String(total));
  }, [open, total]);

  const tenders = useMemo(() => [{ method: "cash", amount: paid }], [paid]);
  const result = useMemo(() => settle({ total, tenders }), [total, tenders]);
  const gap = Math.round((Number(paid || 0) - Number(total)) * 100) / 100;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إتمام عملية البيع</DialogTitle>
          <DialogDescription>
            العميل: {customerName} • الإجمالي المستحق {fmtMoney(Number(total))}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label htmlFor="paid-amount" className="mb-1.5 block text-xs text-muted-foreground">المبلغ المدفوع</label>
            <Input
              id="paid-amount"
              aria-label="المبلغ المدفوع"
              type="number"
              min={0}
              step="0.01"
              autoFocus
              value={paid}
              onChange={(e) => setPaid(e.target.value)}
              className="num h-10 text-lg font-bold"
            />
          </div>

          <div className={cn("num flex items-center justify-between rounded-xl border p-3 text-sm font-bold", result.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-800")}>
            <span>{result.ok ? (Number(result.change) > 0 ? "الباقي للعميل" : "المبلغ مطابق") : gap < 0 ? "المتبقي على العميل" : "تعذّر الإتمام"}</span>
            <span>{result.ok ? fmtMoney(Number(result.change)) : gap < 0 ? fmtMoney(Math.abs(gap)) : "—"}</span>
          </div>
          {!result.ok && gap >= 0 && result.reason ? <p role="alert" className="text-xs font-semibold text-rose-600">{result.reason}</p> : null}
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              رجوع للفاتورة
            </Button>
            <Button className="h-9 flex-1 font-bold" disabled={!result.ok || pending} onClick={() => onConfirm(tenders)}>
              {pending ? "جارٍ إتمام البيع…" : "تأكيد البيع وطباعة الفاتورة"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
