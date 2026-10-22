import React from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { fmtMoney } from "@/cashier/lib/format";

/**
 * The inside of the confirm dialog, apart from the Radix wrapper (which renders in a portal and so
 * cannot be rendered on the server in a unit test). The cashier records the sale; the system does
 * not take or count money: no amount paid, no change, no payment method. `total` is the backend quote.
 */
export function ConfirmSaleBody({ total, onBack, onConfirm, pending = false, error = null }) {
  return (
    <div className="space-y-3">
      <div className="num flex items-center justify-between rounded-xl border border-border bg-muted/40 p-3 text-sm font-bold">
        <span>إجمالي الفاتورة</span>
        <span>{fmtMoney(Number(total))}</span>
      </div>
      {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onBack} disabled={pending}>
          رجوع للفاتورة
        </Button>
        <Button className="h-9 flex-1 font-bold" disabled={pending || !(Number(total) > 0)} onClick={() => onConfirm()} autoFocus>
          {pending ? "جارٍ تسجيل البيع…" : "تأكيد البيع وطباعة الفاتورة"}
        </Button>
      </div>
    </div>
  );
}

export default function ConfirmSaleDialog({ open, onOpenChange, total, customerName, onConfirm, pending = false, error = null }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تأكيد عملية البيع</DialogTitle>
          <DialogDescription>العميل: {customerName}</DialogDescription>
        </DialogHeader>
        <ConfirmSaleBody total={total} onBack={() => onOpenChange(false)} onConfirm={onConfirm} pending={pending} error={error} />
      </DialogContent>
    </Dialog>
  );
}
