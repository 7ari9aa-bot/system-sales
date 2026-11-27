import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { buildPayment, parsePayment } from "@/cashier/api/purchasingAdapter";
import { PAYMENT_METHODS as LABELS, fmtMoney } from "@/cashier/lib/format";
import { toMinor } from "@/cashier/api/money";

const METHODS = ["cash", "card", "wallet", "bank_transfer"];

// تسجيل دفعة لمورد: على فاتورة بعينها (لو اتحدد order) أو على الحساب.
// النقدي من الدرج بيسجّل حركة خروج على درج الوردية المفتوحة؛ غير كده بيتسجّل في الدفاتر من غير وردية.
export default function SupplierPaymentDialog({ open, onOpenChange, supplier, order, onSubmit, pending, error, sessionId = null }) {
  const owed = order ? order.balance : null;
  const [form, setForm] = useState({ amount: "", method: "bank_transfer", note: "", fromDrawer: false });
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    // A shop with an open drawer most likely pays its suppliers' petty cash from it.
    setForm({ amount: owed && toMinor(owed) > 0 ? owed : "", method: "cash", note: "", fromDrawer: Boolean(sessionId) });
    setLocalError("");
  }, [open, owed, sessionId]);

  if (!supplier) return null;
  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const amount = parsePayment(form.amount);

  function submit() {
    const built = buildPayment({ supplierId: supplier.id, orderId: order?.id, ...form }, { owed, sessionId });
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
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">دفعة لـ {supplier.name}</DialogTitle>
          <DialogDescription>
            {order ? `على الفاتورة ${order.number}. المتبقي ${fmtMoney(order.balance)}.` : `على حساب المورد. المستحق الحالي ${fmtMoney(supplier.balance)}.`}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">المبلغ</Label>
            <Input inputMode="decimal" className="num" value={form.amount} onChange={(e) => set("amount", e.target.value)} placeholder="0.00" autoFocus />
          </div>
          {form.method === "cash" ? (
            <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-[12px]">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[#F97316]"
                checked={Boolean(form.fromDrawer) && Boolean(sessionId)}
                disabled={!sessionId}
                onChange={(e) => set("fromDrawer", e.target.checked)}
              />
              <span>
                <span className="font-semibold">الدفع من درج الوردية المفتوحة</span>
                <span className="block text-[11px] text-muted-foreground">
                  {sessionId ? "هيتسجّل خروج نقدي من الدرج ويظهر في حساب الإقفال." : "لا توجد وردية مفتوحة: ستُسجَّل الدفعة من خارج الدرج."}
                </span>
              </span>
            </label>
          ) : null}

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">طريقة الدفع</Label>
            <Select value={form.method} onValueChange={(v) => set("method", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {METHODS.map((m) => <SelectItem key={m} value={m}>{LABELS[m]?.label ?? m}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">ملاحظة (اختياري)</Label>
            <Input value={form.note} maxLength={255} onChange={(e) => set("note", e.target.value)} />
          </div>
        </div>
        {shown && <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">{shown}</p>}
        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">المبلغ: <span className="font-bold text-foreground">{amount ? fmtMoney(amount) : "—"}</span></p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>رجوع</Button>
            <Button className="font-bold" disabled={pending} onClick={submit}>{pending ? "جارٍ التسجيل..." : "تسجيل الدفعة"}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
