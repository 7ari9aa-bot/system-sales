import { useEffect, useRef, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { newIntent } from "@/cashier/api/posApi";
import { MOVEMENT_KINDS, planMovement } from "@/cashier/api/drawerMovement";
import { fmtMoney } from "@/cashier/lib/format";

// حركة نقدية يدوية على الوردية المفتوحة: إيداع، مصروف، أو سحب للخزنة الرئيسية.
// السجل في الباك للإضافة فقط، فلا تعديل ولا حذف: التصحيح يكون بحركة عكسية.
export default function CashMovementDialog({ open, onOpenChange, shift, expectedCash, onSubmit, pending = false, error = null }) {
  const [kind, setKind] = useState("pay_out");
  const [amount, setAmount] = useState("");
  const intent = useRef(null);
  const inFlight = useRef(false); // synchronous guard: state updates land a frame too late for a fast double-click

  useEffect(() => {
    if (open) {
      setKind("pay_out");
      setAmount("");
      intent.current = newIntent(); // one intent per opening; reused on retry
      inFlight.current = false;
    }
  }, [open]);

  const plan = planMovement({ kind, amount, expectedCash });
  const touched = amount !== "";
  const canSubmit = plan.ok && !pending;

  useEffect(() => {
    if (!pending) inFlight.current = false; // finished (ok or failed): a retry may go out, with the SAME intent
  }, [pending]);

  function confirm() {
    if (!plan.ok || inFlight.current) return;
    inFlight.current = true;
    onSubmit({ ...plan, intent: intent.current });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">حركة نقدية على الوردية</DialogTitle>
          <DialogDescription>
            {shift ? `الوردية ${shift.number}. ` : ""}تُسجَّل الحركة نهائيًا ولا يمكن تعديلها أو حذفها، وتدخل في حساب المتوقع في الخزنة.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <fieldset className="grid gap-2" aria-label="نوع الحركة">
            {MOVEMENT_KINDS.map((k) => (
              <label key={k.kind} className="flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-sm has-[:checked]:border-primary">
                <input type="radio" name="movement-kind" value={k.kind} checked={kind === k.kind} onChange={() => setKind(k.kind)} className="mt-1" />
                <span>
                  <span className="font-semibold">{k.label}</span>
                  <span className="block text-xs text-muted-foreground">{k.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div>
            <Label htmlFor="movement-amount" className="mb-1.5 block text-xs text-muted-foreground">المبلغ</Label>
            <Input id="movement-amount" inputMode="decimal" autoComplete="off" value={amount} onChange={(e) => setAmount(e.target.value)} className="num" />
          </div>
          {touched && !plan.ok ? <p role="alert" className="text-xs font-semibold text-amber-700">{plan.error}</p> : null}
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
        </div>

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <p className="num text-xs text-muted-foreground">
            المتوقع الآن: <span className="font-bold text-foreground">{expectedCash != null ? fmtMoney(Number(expectedCash)) : "غير متاح"}</span>
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>إلغاء</Button>
            <Button className="font-bold" disabled={!canSubmit} onClick={confirm}>
              {pending ? "جارٍ التسجيل…" : "تسجيل الحركة"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
