import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { fmtMoney } from "@/cashier/lib/format";

const EMPTY = { openingCash: "0" };

// فتح وردية جديدة: الموظف المسؤول ورصيد البداية في الخزنة.
export default function ShiftOpenDialog({ open, onOpenChange, onSubmit, pending = false, error = null }) {
  const [form, setForm] = useState(EMPTY);

  useEffect(() => {
    if (open) setForm(EMPTY);
  }, [open]);

  const opening = Number(form.openingCash) || 0;
  const canSubmit = opening >= 0 && !pending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">فتح وردية جديدة</DialogTitle>
          <DialogDescription>تُفتح الوردية باسم المستخدم الحالي. حدّد رصيد البداية الموجود في الخزنة قبل بدء البيع.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">رصيد البداية في الخزنة</Label>
            <Input type="number" min={0} value={form.openingCash} onChange={(e) => setForm((prev) => ({ ...prev, openingCash: e.target.value }))} className="num" />
          </div>
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
        </div>

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">
            رصيد الافتتاح: <span className="font-bold text-foreground">{fmtMoney(opening)}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              إلغاء
            </Button>
            <Button
              className="font-bold"
              disabled={!canSubmit}
              onClick={() => onSubmit({ openingCash: opening })}
            >
              {pending ? "جارٍ الفتح…" : "فتح الوردية"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}