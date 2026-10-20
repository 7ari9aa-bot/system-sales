import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { buildVoid } from "@/cashier/api/expensesAdapter";
import { fmtMoney } from "@/cashier/lib/format";

// إلغاء مصروف مسجَّل: السبب إجباري، والمصروف يفضل ظاهر في السجل بحالة "ملغي" (مفيش حذف).
export default function VoidExpenseDialog({ expense, onOpenChange, onSubmit, pending, error }) {
  const [reason, setReason] = useState("");
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setReason("");
    setLocalError("");
  }, [expense?.id]);

  function submit() {
    const built = buildVoid(reason);
    if (!built.ok) {
      setLocalError(built.error);
      return;
    }
    setLocalError("");
    onSubmit(built.payload.reason);
  }

  const shown = localError || error;

  return (
    <Dialog open={Boolean(expense)} onOpenChange={(open) => !pending && onOpenChange(open)}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إلغاء المصروف {expense?.number}؟</DialogTitle>
          <DialogDescription className="leading-relaxed">
            مبلغ {expense ? fmtMoney(expense.amount) : ""} هيتشال من الإجماليات.
            {expense?.payment === "cash" ? " وهيرجع للدرج لو الوردية لسه مفتوحة." : ""} المصروف نفسه بيفضل ظاهر في السجل بحالة «ملغي».
          </DialogDescription>
        </DialogHeader>
        <div>
          <Label className="mb-1.5 block text-xs text-muted-foreground">سبب الإلغاء</Label>
          <Input
            value={reason}
            maxLength={255}
            autoFocus
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !pending && submit()}
            placeholder="مثال: اتسجل بالغلط"
          />
        </div>
        {shown && (
          <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">
            {shown}
          </p>
        )}
        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            رجوع
          </Button>
          <Button className="bg-destructive font-bold text-destructive-foreground hover:bg-destructive/90" disabled={pending} onClick={submit}>
            {pending ? "جارٍ الإلغاء..." : "إلغاء المصروف"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
