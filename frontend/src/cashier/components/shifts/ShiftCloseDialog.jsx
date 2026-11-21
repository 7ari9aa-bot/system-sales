import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Textarea } from "@/cashier/components/ui/textarea";
import { fmtMoney, fmtMoneyDeduction } from "@/cashier/lib/format";
import { closeProblems, countsDrawer, gapMinor } from "@/cashier/api/closePlan";

// إغلاق اليوم: تسجيل لما حدث فقط (رصيد البداية + الفواتير − المرتجعات)، وليس جردًا للدرج.
// `preview` = the backend's close-preview (every figure computed from the ledger, not on the client).
/** Arabic number agreement: 1 = singular, 2 = dual, 3-10 = plural noun, 11+ = singular noun. */
export function heldInvoicesPhrase(n) {
  if (n === 1) return "توجد فاتورة معلقة";
  if (n === 2) return "توجد فاتورتان معلقتان";
  if (n >= 3 && n <= 10) return `توجد ${n} فواتير معلقة`;
  return `توجد ${n} فاتورة معلقة`;
}

export default function ShiftCloseDialog({ open, onOpenChange, shift, heldCount = 0, preview, previewLoading = false, onSubmit, pending = false, error = null, drawer = null, rules = null }) {
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  if (!shift) return null;

  // A till that takes payments has a drawer to count. One that does not closes exactly as it always has.
  const tillRules = { take_payments: preview?.take_payments };
  const counts = countsDrawer(tillRules);
  const expected = drawer?.expected_cash ?? null;
  const gap = gapMinor(counted, expected);
  const problems = closeProblems({
    rules: tillRules,
    counted,
    expected,
    reason,
    reasonRequired: rules?.reasonRequired ?? true,
    threshold: rules?.threshold ?? 0,
    // Whether this user is a manager is the server's call: it refuses a gap over the limit with the reason why.
    canApprove: true,
  });
  const needsReason = counts && gap !== null && gap !== 0 && (rules?.reasonRequired ?? true);

  const ready = Boolean(preview) && !previewLoading;
  const money = (v) => (ready ? fmtMoney(Number(v ?? 0)) : "…");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إغلاق اليوم {shift.number}</DialogTitle>
          <DialogDescription>
            {shift.employee} • رصيد البداية {fmtMoney(shift.openingCash)} • رصيد نهاية اليوم {money(preview?.closing_balance)}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs">
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">رصيد بداية اليوم</span>
              <span>{money(preview?.opening_balance ?? shift.openingCash)}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">إجمالي الفواتير ({ready ? preview.invoice_count : "…"})</span>
              <span>{money(preview?.sales_total)}</span>
            </div>
            <div className="num flex justify-between py-0.5">
              <span className="text-muted-foreground">إجمالي المرتجعات ({ready ? preview.return_count : "…"})</span>
              <span className="text-rose-600">{ready ? fmtMoneyDeduction(preview?.returns_total) : "…"}</span>
            </div>
            <div className="num mt-1 flex justify-between border-t border-border pt-1.5 font-bold">
              <span>رصيد نهاية اليوم</span>
              <span>{money(preview?.closing_balance)}</span>
            </div>
          </div>
          {counts ? (
            <div className="grid gap-2 rounded-xl border border-border p-3 text-xs" data-testid="drawer-count">
              <div className="num flex justify-between py-0.5">
                <span className="text-muted-foreground">المتوقع في الدرج</span>
                <span>{expected == null ? "…" : fmtMoney(Number(expected))}</span>
              </div>
              <label className="grid gap-1">
                <span className="font-semibold">النقدية الفعلية في الدرج (عدّها بإيدك)</span>
                <Input inputMode="decimal" dir="ltr" value={counted} onChange={(e) => setCounted(e.target.value)} placeholder="0.00" aria-label="النقدية الفعلية" />
              </label>
              {gap !== null ? (
                <div className={`num flex justify-between font-bold ${gap === 0 ? "text-emerald-600" : "text-rose-600"}`} data-testid="drawer-gap">
                  <span>{gap === 0 ? "الدرج مطابق" : gap < 0 ? "عجز" : "زيادة"}</span>
                  <span>{gap === 0 ? "" : fmtMoney(Math.abs(gap) / 100)}</span>
                </div>
              ) : null}
              {needsReason ? (
                <label className="grid gap-1">
                  <span className="font-semibold">سبب الفرق (مطلوب)</span>
                  <Textarea rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} aria-label="سبب الفرق" />
                </label>
              ) : null}
              {gap !== null && gap !== 0 && (rules?.threshold ?? 0) > 0 && Math.abs(gap) > Math.round(rules.threshold * 100) ? (
                <p className="text-[11px] leading-relaxed text-amber-700">الفرق أكبر من الحد المسموح ({fmtMoney(rules.threshold)}): الإغلاق يحتاج مديرًا بصلاحية الموافقة.</p>
              ) : null}
            </div>
          ) : (
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              الإغلاق يسجّل ما حدث في اليوم فقط. لا يُطلب عدّ الدرج ولا يُحسب عجز أو زيادة.
            </p>
          )}

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
            disabled={!ready || pending || (counts && (expected == null || problems.length > 0))}
            onClick={() => onSubmit(counts ? { counted, expected, reason } : undefined)}
          >
            {pending ? "جارٍ الإغلاق…" : heldCount > 0 ? "تأكيد الإغلاق وتصفير المعلقة" : "تأكيد إغلاق اليوم"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}