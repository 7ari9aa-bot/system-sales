import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { useApprovers } from "@/cashier/api/useApprovers";
import { pinProblem } from "@/cashier/api/approval";

// موافقة المدير: الكاشير يختار المدير ويكتب الـPIN بتاعه. الـPIN لا يُخزَّن ولا يُعرض ولا يبقى
// في الذاكرة بعد الإغلاق، ويُرسَل مع نفس الطلب فقط.
export default function ManagerApprovalDialog({ open, reason, onCancel, onApprove, pending = false, error = null }) {
  const approvers = useApprovers(open);
  const [managerId, setManagerId] = useState("");
  const [pin, setPin] = useState("");
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (open) {
      setPin("");
      setTouched(false);
    }
  }, [open]);

  const list = approvers.data ?? [];
  useEffect(() => {
    if (open && !managerId && list.length === 1) setManagerId(list[0].id);
  }, [open, managerId, list]);

  const problem = pinProblem(pin) ?? (managerId ? null : "اختر المدير");
  const submit = () => {
    setTouched(true);
    if (problem || pending) return;
    onApprove({ managerId, pin });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !pending && onCancel()}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تحتاج موافقة مدير</DialogTitle>
          <DialogDescription>{reason}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          {approvers.isLoading ? <p className="text-xs text-muted-foreground">جارٍ تحميل المديرين…</p> : null}
          {!approvers.isLoading && list.length === 0 ? (
            <p role="alert" className="text-xs font-semibold text-amber-700">
              لا يوجد مدير مفعّل له رقم PIN. اطلب من المالك أن يضبط PIN من الإعدادات، أو ينفّذ العملية بنفسه.
            </p>
          ) : (
            <>
              <div>
                <Label htmlFor="approver" className="mb-1.5 block text-xs text-muted-foreground">المدير</Label>
                <select
                  id="approver"
                  value={managerId}
                  onChange={(e) => setManagerId(e.target.value)}
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                >
                  <option value="">اختر المدير</option>
                  {list.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="approver-pin" className="mb-1.5 block text-xs text-muted-foreground">رقم PIN المدير</Label>
                <Input
                  id="approver-pin"
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={8}
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && submit()}
                  className="num"
                />
              </div>
            </>
          )}
          {touched && problem ? <p role="alert" className="text-xs font-semibold text-amber-700">{problem}</p> : null}
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={pending} onClick={onCancel}>إلغاء</Button>
          <Button className="font-bold" disabled={pending || list.length === 0} onClick={submit}>
            {pending ? "جارٍ الاعتماد…" : "اعتماد"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
