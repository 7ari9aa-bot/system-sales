import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { employees } from "@/cashier/lib/mockData";
import { EXPENSE_CATEGORIES, EXPENSE_PAYMENTS } from "@/cashier/lib/storeOpsData";
import { PAYMENT_METHODS, fmtMoney } from "@/cashier/lib/format";

const today = () => new Date().toISOString().slice(0, 10);

// تسجيل أو تعديل مصروف: التصنيف والبيان والمبلغ والتاريخ وطريقة الدفع.
export default function ExpenseDialog({ open, onOpenChange, expense, onSubmit }) {
  const [form, setForm] = useState({ category: "", description: "", amount: "", payment: "cash", date: today(), employee: employees[1].name });

  useEffect(() => {
    if (!open) return;
    setForm(
      expense
        ? { ...expense, amount: String(expense.amount), date: String(expense.date).slice(0, 10) }
        : { category: "", description: "", amount: "", payment: "cash", date: today(), employee: employees[1].name },
    );
  }, [open, expense]);

  const amount = Number(form.amount) || 0;
  const canSubmit = Boolean(form.category && form.description.trim() && amount > 0 && form.date);

  function set(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function submit() {
    onSubmit({
      ...(expense ? { id: expense.id, number: expense.number } : {}),
      category: form.category,
      description: form.description.trim(),
      amount: +amount.toFixed(2),
      payment: form.payment,
      date: `${form.date}T${new Date().toTimeString().slice(0, 5)}:00`,
      employee: form.employee,
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{expense ? "تعديل مصروف" : "تسجيل مصروف جديد"}</DialogTitle>
          <DialogDescription>سجّل المصروف بتصنيفه ومبلغه وطريقة دفعه ليُخصم من خزنة الوردية.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">التصنيف</Label>
            <Select value={form.category || "none"} onValueChange={(v) => set("category", v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="اختر التصنيف" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر التصنيف</SelectItem>
                {EXPENSE_CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المبلغ</Label>
            <Input type="number" min={0} value={form.amount} onChange={(e) => set("amount", e.target.value)} className="num" />
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">البيان</Label>
            <Input value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="مثال: فاتورة الكهرباء" />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">تاريخ المصروف</Label>
            <Input type="date" value={form.date} onChange={(e) => set("date", e.target.value)} />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">طريقة الدفع</Label>
            <Select value={form.payment} onValueChange={(v) => set("payment", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPENSE_PAYMENTS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {PAYMENT_METHODS[p]?.label ?? p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">الموظف المسؤول</Label>
            <Select value={form.employee} onValueChange={(v) => set("employee", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {employees.map((e) => (
                  <SelectItem key={e.id} value={e.name}>
                    {e.name} — {e.job}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">
            المبلغ: <span className="font-bold text-foreground">{fmtMoney(amount)}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              إلغاء
            </Button>
            <Button className="font-bold" disabled={!canSubmit} onClick={submit}>
              {expense ? "حفظ التعديل" : "تسجيل المصروف"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}