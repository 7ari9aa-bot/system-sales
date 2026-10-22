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

// تسجيل دفعة لمورد: على فاتورة بعينها (لو اتحدد order) أو على الحساب. النقدي بيتسجّل حتى من غير وردية.
export default function SupplierPaymentDialog({ open, onOpenChange, supplier, order, openSessionId, onSubmit, pending, error }) {
  const owed = order ? order.balance : null;
  const [form, setForm] = useState({ amount: "", method: "bank_transfer", note: "" });
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    setForm({ amount: owed && toMinor(owed) > 0 ? owed : "", method: "cash", note: "" });
    setLocalError("");
  }, [open, owed]);

  if (!supplier) return null;
  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));
  const amount = parsePayment(form.amount);
  const cashWithoutShift = form.method === "cash" && !openSessionId;

  function submit() {
    const built = buildPayment({ supplierId: supplier.id, orderId: order?.id, ...form }, { openSessionId, owed });
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
        {cashWithoutShift && (
          <p role="status" className="rounded-md border border-[#EBD9A8] bg-[#FFF8E5] px-3 py-2 text-xs font-semibold text-[#8A6100]">
            مفيش وردية مفتوحة: الدفعة هتتسجّل، لكن ما هتتخصمش من درج. لو دفعتها من درج وردية، افتحها الأول.
          </p>
        )}
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
