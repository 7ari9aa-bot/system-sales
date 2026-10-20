import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Textarea } from "@/cashier/components/ui/textarea";
import { employees } from "@/cashier/lib/mockData";
import { fmtMoney } from "@/cashier/lib/format";

const EMPTY = { employee: "", openingCash: "1500", note: "" };

// فتح وردية جديدة: الموظف المسؤول ورصيد البداية في الخزنة.
export default function ShiftOpenDialog({ open, onOpenChange, onSubmit }) {
  const [form, setForm] = useState(EMPTY);

  useEffect(() => {
    if (open) setForm(EMPTY);
  }, [open]);

  const opening = Number(form.openingCash) || 0;
  const canSubmit = Boolean(form.employee);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">فتح وردية جديدة</DialogTitle>
          <DialogDescription>حدّد الموظف المسؤول ورصيد البداية الموجود في الخزنة قبل بدء البيع.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">الموظف المسؤول</Label>
            <Select value={form.employee || "none"} onValueChange={(v) => setForm((prev) => ({ ...prev, employee: v === "none" ? "" : v }))}>
              <SelectTrigger>
                <SelectValue placeholder="اختر الموظف" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر الموظف</SelectItem>
                {employees
                  .filter((e) => e.status === "active")
                  .map((e) => (
                    <SelectItem key={e.id} value={e.name}>
                      {e.name} — {e.job}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">رصيد البداية في الخزنة</Label>
            <Input type="number" min={0} value={form.openingCash} onChange={(e) => setForm((prev) => ({ ...prev, openingCash: e.target.value }))} className="num" />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظات</Label>
            <Textarea rows={2} value={form.note} onChange={(e) => setForm((prev) => ({ ...prev, note: e.target.value }))} placeholder="مثال: وردية صباحية" />
          </div>
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
              onClick={() => {
                onSubmit({ employee: form.employee, openingCash: opening, note: form.note });
                onOpenChange(false);
              }}
            >
              فتح الوردية
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}