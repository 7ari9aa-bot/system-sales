import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Textarea } from "@/cashier/components/ui/textarea";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// إغلاق الوردية: مقارنة النقدية المتوقعة بالمبلغ الفعلي المعدود وحساب الفرق.
export default function ShiftCloseDialog({ open, onOpenChange, shift, onSubmit }) {
  const [actual, setActual] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (open && shift) {
      setActual(String(shift.expected));
      setNote("");
    }
  }, [open, shift]);

  if (!shift) return null;

  const counted = Number(actual) || 0;
  const difference = +(counted - shift.expected).toFixed(2);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إغلاق الوردية {shift.number}</DialogTitle>
          <DialogDescription>
            {shift.employee} • رصيد البداية {fmtMoney(shift.openingCash)} • النقدية المتوقعة {fmtMoney(shift.expected)}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs">
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">مبيعات نقدية</span>
              <span>{fmtMoney(shift.cashSales)}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">مرتجعات نقدية</span>
              <span className="text-rose-600">−{fmtMoney(shift.returnsCash)}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">مصروفات نقدية</span>
              <span className="text-rose-600">−{fmtMoney(shift.expensesCash)}</span>
            </div>
            <div className="num mt-1 flex justify-between border-t border-border pt-1.5 font-bold">
              <span>المتوقع في الخزنة</span>
              <span>{fmtMoney(shift.expected)}</span>
            </div>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">النقدية الفعلية المعدودة</Label>
            <Input type="number" min={0} value={actual} onChange={(e) => setActual(e.target.value)} className="num" />
          </div>

          <div
            className={cn(
              "num flex items-center justify-between rounded-xl border p-3 text-sm font-bold",
              difference === 0 ? "border-emerald-200 bg-emerald-50 text-emerald-700" : difference > 0 ? "border-sky-200 bg-sky-50 text-sky-700" : "border-rose-200 bg-rose-50 text-rose-700",
            )}
          >
            <span>{difference === 0 ? "الخزنة مطابقة" : difference > 0 ? "فرق زيادة" : "فرق عجز"}</span>
            <span>{difference > 0 ? `+${fmtMoney(difference)}` : fmtMoney(difference)}</span>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظة الإغلاق</Label>
            <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="سبب الفرق إن وُجد" />
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            إلغاء
          </Button>
          <Button
            className="font-bold"
            onClick={() => {
              onSubmit({ actual: counted, note });
              onOpenChange(false);
            }}
          >
            تأكيد إغلاق الوردية
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}