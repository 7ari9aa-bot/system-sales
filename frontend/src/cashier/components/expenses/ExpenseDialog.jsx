import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { buildExpense, normalizeAmountInput } from "@/cashier/api/expensesAdapter";
import { PAYMENT_METHODS, fmtMoney } from "@/cashier/lib/format";
import { shopToday } from "@/cashier/lib/period";

const today = () => shopToday();
const blank = () => ({ categoryId: "", description: "", amount: "", payment: "cash", date: today() });

// تسجيل مصروف جديد. المصروف المسجَّل ما بيتعدّلش: التصحيح بإلغائه وتسجيل مصروف صحيح.
// النقدي مسجَّل بدون وردية. لو فيه وردية مفتوحة بيتحسب على درجها، وإلا بيتسجَّل فقط.
export default function ExpenseDialog({ open, onOpenChange, categories, methods, openSessionId, onSubmit, pending, error }) {
  const [form, setForm] = useState(blank);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    setForm({ ...blank(), payment: "cash" });
    setLocalError("");
  }, [open]);

  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const amount = normalizeAmountInput(form.amount);
  const cashWithoutShift = form.payment === "cash" && !openSessionId;
  const built = buildExpense(form, { openSessionId });

  function submit() {
    if (!built.ok) {
      setLocalError(built.error);
      return;
    }
    setLocalError("");
    onSubmit(built.payload);
  }

  const shown = localError || error;

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تسجيل مصروف جديد</DialogTitle>
          <DialogDescription>
            المصروف النقدي بيتسجّل حتى من غير وردية. وبعد التسجيل ما بيتعدّلش: لو غلطت، ألغيه وسجّله صح.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">التصنيف</Label>
            <Select value={form.categoryId || "none"} onValueChange={(v) => set("categoryId", v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="اختر التصنيف" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">اختر التصنيف</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المبلغ</Label>
            <Input inputMode="decimal" value={form.amount} onChange={(e) => set("amount", e.target.value)} className="num" placeholder="0.00" />
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">البيان</Label>
            <Input value={form.description} maxLength={255} onChange={(e) => set("description", e.target.value)} placeholder="مثال: فاتورة الكهرباء" />
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
                {methods.map((p) => (
                  <SelectItem key={p} value={p}>
                    {PAYMENT_METHODS[p]?.label ?? p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {cashWithoutShift && (
          <p role="status" className="rounded-md border border-[#EBD9A8] bg-[#FFF8E5] px-3 py-2 text-xs font-semibold text-[#8A6100]">
            مفيش وردية مفتوحة: المصروف هيتسجّل، لكن ما هيتخصمش من درج. لو دفعته من درج وردية، افتحها الأول.
          </p>
        )}
        {shown && (
          <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">
            {shown}
          </p>
        )}

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">
            المبلغ: <span className="font-bold text-foreground">{amount ? fmtMoney(amount) : "—"}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
              رجوع
            </Button>
            <Button className="font-bold" disabled={pending} onClick={submit}>
              {pending ? "جارٍ التسجيل..." : "تسجيل المصروف"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
