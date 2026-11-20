import React, { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { fmtMoney } from "@/cashier/lib/format";
import { Input } from "@/cashier/components/ui/input";
import { buildTender, canSellOnAccount, changeDue, defaultTender, remainingToPay } from "@/cashier/api/tenderPlan";

const METHOD_LABEL = { cash: "نقدي", card: "بطاقة", transfer: "تحويل", wallet: "محفظة" };
const label = (m) => METHOD_LABEL[m] ?? m;

/**
 * The inside of the confirm dialog, apart from the Radix wrapper (which renders in a portal and so
 * cannot be rendered on the server in a unit test). The cashier records the sale; the system does
 * not take or count money: no amount paid, no change, no payment method. `total` is the backend quote.
 */
export function ConfirmSaleBody({ total, onBack, onConfirm, pending = false, error = null, rules = null, customer = {}, initialLines = null }) {
  const recording = Boolean(rules?.take_payments);
  const [lines, setLines] = useState(() => initialLines ?? defaultTender(rules, total));
  const [onAccount, setOnAccount] = useState(false);
  const accountOk = canSellOnAccount(rules, customer);

  const plan = recording ? buildTender(rules, total, lines, { onAccount: onAccount && accountOk }) : { ok: true, payload: {} };
  const left = recording ? remainingToPay(total, lines) : "0.00";
  const change = recording ? changeDue(lines) : "0.00";
  const patch = (i, next) => setLines((all) => all.map((l, j) => (j === i ? { ...l, ...next } : l)));
  const unused = recording ? (rules.methods ?? []).filter((m) => !lines.some((l) => l.method === m)) : [];

  return (
    <div className="space-y-3">
      <div className="num flex items-center justify-between rounded-xl border border-border bg-muted/40 p-3 text-sm font-bold">
        <span>إجمالي الفاتورة</span>
        <span>{fmtMoney(Number(total))}</span>
      </div>

      {recording ? (
        <div className="space-y-2" aria-label="طريقة الدفع">
          <p className="text-xs font-bold text-muted-foreground">طريقة الدفع</p>
          {lines.map((l, i) => (
            <div key={`${l.method}-${i}`} className="space-y-1 rounded-lg border border-border p-2">
              <div className="flex items-center gap-2">
                <span className="w-16 text-sm font-semibold">{label(l.method)}</span>
                <Input dir="ltr" inputMode="decimal" className="num h-8 flex-1" value={l.amount} aria-label={`مبلغ ${label(l.method)}`} onChange={(e) => patch(i, { amount: e.target.value })} />
                {lines.length > 1 ? (
                  <Button type="button" variant="ghost" className="h-8 px-2" aria-label="حذف" onClick={() => setLines((all) => all.filter((_, j) => j !== i))}>×</Button>
                ) : null}
              </div>
              {l.method === "cash" ? (
                <Input dir="ltr" inputMode="decimal" className="num h-8" placeholder="المبلغ المستلم (اختياري)" value={l.tendered} aria-label="المبلغ المستلم" onChange={(e) => patch(i, { tendered: e.target.value })} />
              ) : null}
              {(rules.reference_required ?? []).includes(l.method) ? (
                <Input dir="ltr" className="h-8" placeholder="رقم المرجع" value={l.reference} aria-label="رقم المرجع" onChange={(e) => patch(i, { reference: e.target.value })} />
              ) : null}
            </div>
          ))}
          {unused.length ? (
            <div className="flex flex-wrap gap-2">
              {unused.map((m) => (
                <Button key={m} type="button" variant="outline" className="h-7 px-2 text-xs" onClick={() => setLines((all) => [...all, { method: m, amount: left === "0.00" ? "" : left, tendered: "", reference: "" }])}>
                  + {label(m)}
                </Button>
              ))}
            </div>
          ) : null}
          <div className="num flex items-center justify-between text-xs">
            <span>المتبقي</span>
            <span className="font-bold">{left}</span>
          </div>
          {Number(change) > 0 ? (
            <div className="num flex items-center justify-between text-xs">
              <span>الباقي للعميل</span>
              <span className="font-bold">{change}</span>
            </div>
          ) : null}
          {accountOk ? (
            <label className="flex items-center gap-2 text-xs font-semibold">
              <input type="checkbox" checked={onAccount} onChange={(e) => setOnAccount(e.target.checked)} />
              <span>الباقي على الحساب</span>
            </label>
          ) : null}
          {!plan.ok ? <p className="text-xs text-muted-foreground">{plan.message}</p> : null}
        </div>
      ) : null}

      {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

      <div className="flex gap-2">
        <Button variant="outline" className="flex-1" onClick={onBack} disabled={pending}>
          رجوع للفاتورة
        </Button>
        <Button className="h-9 flex-1 font-bold" disabled={pending || !(Number(total) > 0) || !plan.ok} onClick={() => onConfirm(plan.payload)} autoFocus>
          {pending ? "جارٍ تسجيل البيع…" : "تأكيد البيع وطباعة الفاتورة"}
        </Button>
      </div>
    </div>
  );
}

export default function ConfirmSaleDialog({ open, onOpenChange, total, customerName, onConfirm, pending = false, error = null, rules = null, customer = {} }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تأكيد عملية البيع</DialogTitle>
          <DialogDescription>العميل: {customerName}</DialogDescription>
        </DialogHeader>
        <ConfirmSaleBody key={`${total}`} total={total} onBack={() => onOpenChange(false)} onConfirm={onConfirm} pending={pending} error={error} rules={rules} customer={customer} />
      </DialogContent>
    </Dialog>
  );
}
