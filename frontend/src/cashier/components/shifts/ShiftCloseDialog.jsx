import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// إغلاق الوردية: مقارنة النقدية المتوقعة بالمبلغ الفعلي المعدود وحساب الفرق.
// `preview` = the backend's close-preview (expected cash computed from the ledger, not on the client).
/** Arabic number agreement: 1 = singular, 2 = dual, 3-10 = plural noun, 11+ = singular noun. */
export function heldInvoicesPhrase(n) {
  if (n === 1) return "توجد فاتورة معلقة";
  if (n === 2) return "توجد فاتورتان معلقتان";
  if (n >= 3 && n <= 10) return `توجد ${n} فواتير معلقة`;
  return `توجد ${n} فاتورة معلقة`;
}

export default function ShiftCloseDialog({ open, onOpenChange, shift, heldCount = 0, preview, previewLoading = false, onSubmit, pending = false, error = null }) {
  const [actual, setActual] = useState("");

  const cash = preview?.by_method?.find((m) => m.method === "cash");
  const expected = cash ? Number(cash.expected) : null;
  const cashIn = Number(preview?.cash_in ?? 0);
  const cashOut = Number(preview?.cash_out ?? 0);

  useEffect(() => {
    if (open) setActual("");
  }, [open, shift?.id]);

  if (!shift) return null;

  const ready = expected !== null && actual !== "" && Number.isFinite(Number(actual)) && Number(actual) >= 0;
  const counted = Number(actual) || 0;
  const difference = expected === null ? 0 : Math.round((counted - expected) * 100) / 100;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إغلاق الوردية {shift.number}</DialogTitle>
          <DialogDescription>
            {shift.employee} • رصيد البداية {fmtMoney(shift.openingCash)} • النقدية المتوقعة {expected === null ? "…" : fmtMoney(expected)}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs">
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">رصيد البداية</span>
              <span>{fmtMoney(Number(preview?.opening_float ?? shift.openingCash))}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">وارد الخزنة (مبيعات نقدية وإيداعات)</span>
              <span>{fmtMoney(cashIn)}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">منصرف من الخزنة</span>
              <span className="text-rose-600">−{fmtMoney(cashOut)}</span>
            </div>
            <div className="num mt-1 flex justify-between border-t border-border pt-1.5 font-bold">
              <span>المتوقع في الخزنة</span>
              <span>{previewLoading || expected === null ? "…" : fmtMoney(expected)}</span>
            </div>
          </div>

          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">النقدية الفعلية المعدودة</Label>
            <Input type="number" min={0} value={actual} onChange={(e) => setActual(e.target.value)} className="num" />
          </div>

          {ready ? <div
            className={cn(
              "num flex items-center justify-between rounded-xl border p-3 text-sm font-bold",
              difference === 0 ? "border-emerald-200 bg-emerald-50 text-emerald-700" : difference > 0 ? "border-sky-200 bg-sky-50 text-sky-700" : "border-rose-200 bg-rose-50 text-rose-700",
            )}
          >
            <span>{difference === 0 ? "الخزنة مطابقة" : difference > 0 ? "فرق زيادة" : "فرق عجز"}</span>
            <span>{difference > 0 ? `+${fmtMoney(difference)}` : fmtMoney(difference)}</span>
          </div> : null}

          {heldCount > 0 ? (
            <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
              <p className="font-semibold">
                {`تنبيه: ${heldInvoicesPhrase(heldCount)} على هذه الوردية.`}
              </p>
              <p className="mt-1 leading-relaxed">
                عند تأكيد إغلاق الوردية {heldCount === 1 ? "تُصفَّر هذه الفاتورة" : heldCount === 2 ? "تُصفَّر الفاتورتان" : "تُصفَّر هذه الفواتير"} ولا يمكن استرجاعها. إن رغبت في إتمامها فراجعها قبل الإغلاق.
              </p>
              <Link
                to="/cashier/pos?held=1"
                className="mt-2 inline-flex h-8 items-center rounded-md border border-amber-300 bg-white px-3 text-xs font-bold text-amber-900 hover:bg-amber-100"
              >
                مراجعة الفواتير المعلقة
              </Link>
            </div>
          ) : null}
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            إلغاء
          </Button>
          <Button
            className="font-bold"
            disabled={!ready || pending}
            onClick={() => onSubmit({ actual: counted })}
          >
            {pending ? "جارٍ الإغلاق…" : heldCount > 0 ? "تأكيد الإغلاق وتصفير المعلقة" : "تأكيد إغلاق الوردية"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}