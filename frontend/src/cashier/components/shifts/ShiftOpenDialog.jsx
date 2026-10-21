import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { fmtMoney } from "@/cashier/lib/format";
import { useOpenChoice } from "@/cashier/api/useShifts";

const EMPTY = { openingCash: "0", registerId: "" };

// فتح وردية جديدة: الموظف المسؤول ورصيد البداية في الخزنة.
export default function ShiftOpenDialog({ open, onOpenChange, onSubmit, pending = false, error = null }) {
  const [form, setForm] = useState(EMPTY);

  useEffect(() => {
    if (open) setForm(EMPTY);
  }, [open]);

  const choice = useOpenChoice(open);
  const free = choice.data?.status === "choose" ? choice.data.free : [];
  const mustPick = free.length > 1; // one free drawer is taken for you; a real choice is never guessed
  const opening = Number(form.openingCash) || 0;
  const canSubmit = opening >= 0 && !pending && (!mustPick || Boolean(form.registerId));

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
          {mustPick ? (
            <div>
              <Label htmlFor="open-register" className="mb-1.5 block text-xs text-muted-foreground">جهاز الكاشير</Label>
              <select
                id="open-register"
                value={form.registerId}
                onChange={(e) => setForm((prev) => ({ ...prev, registerId: e.target.value }))}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">اختر الجهاز…</option>
                {free.map((r) => (
                  <option key={r.id} value={r.id}>{r.name || r.code}</option>
                ))}
              </select>
            </div>
          ) : choice.data?.status === "none" ? (
            <p role="status" className="text-xs font-semibold text-amber-700">
              {choice.data.reason === "all_busy" ? "كل أجهزة الكاشير عليها ورديات مفتوحة." : "لا يوجد جهاز كاشير نشط بعد؛ سيُجهَّز عند أول فتح."}
            </p>
          ) : null}
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
              onClick={() => onSubmit({ openingCash: opening, registerId: form.registerId || null })}
            >
              {pending ? "جارٍ الفتح…" : "فتح الوردية"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}