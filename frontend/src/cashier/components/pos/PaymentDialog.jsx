import { useEffect, useMemo, useState } from "react";
import { Banknote, CreditCard, Landmark, Plus, Trash2, Wallet } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { settle } from "@/cashier/api/checkout";
import { fmtMoney } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

// Only methods the backend accepts for a sale (cash, card, wallet, bank_transfer). "Credit / on account"
// is NOT here: the backend has no customer ledger yet, so offering it would fail at /sell.
const METHODS = {
  cash: { label: "نقدي", icon: Banknote },
  card: { label: "بطاقة", icon: CreditCard },
  wallet: { label: "محفظة إلكترونية", icon: Wallet },
  bank_transfer: { label: "تحويل بنكي", icon: Landmark },
};

const blank = (method) => ({ method, amount: "" });

// Payment: one or several tenders. `total` is the backend quote, never computed here.
export default function PaymentDialog({ open, onOpenChange, total, allowedMethods = ["cash"], defaultMethod = "cash", customerName, onConfirm, pending = false, error = null }) {
  const methods = allowedMethods.filter((m) => METHODS[m]);
  const first = methods.includes(defaultMethod) ? defaultMethod : methods[0];
  const [rows, setRows] = useState([blank(first)]);

  useEffect(() => {
    // Open with the whole total on the default method: the common one-tap cash sale.
    if (open) setRows([{ method: first, amount: String(total) }]);
  }, [open, first, total]);

  const result = useMemo(() => settle({ total, tenders: rows }), [total, rows]);
  const typed = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  const gap = Math.round((typed - Number(total)) * 100) / 100;

  const setRow = (i, patch) => setRows((prev) => prev.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const usedMethods = rows.map((r) => r.method);
  const nextMethod = methods.find((m) => !usedMethods.includes(m));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">إتمام عملية البيع</DialogTitle>
          <DialogDescription>
            العميل: {customerName} • الإجمالي المستحق {fmtMoney(Number(total))}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {rows.map((row, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_auto] items-center gap-2">
              <select
                aria-label="طريقة الدفع"
                value={row.method}
                onChange={(e) => setRow(i, { method: e.target.value })}
                className="h-9 rounded-md border border-border bg-background px-2 text-sm"
              >
                {methods.map((m) => (
                  <option key={m} value={m} disabled={m !== row.method && usedMethods.includes(m)}>
                    {METHODS[m].label}
                  </option>
                ))}
              </select>
              <Input aria-label="المبلغ" type="number" min={0} step="0.01" value={row.amount} onChange={(e) => setRow(i, { amount: e.target.value })} className="num h-9 font-bold" />
              <Button variant="ghost" size="icon" aria-label="حذف طريقة الدفع" disabled={rows.length === 1} onClick={() => setRows((prev) => prev.filter((_, k) => k !== i))}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}

          {nextMethod ? (
            <Button variant="outline" size="sm" onClick={() => setRows((prev) => [...prev, { method: nextMethod, amount: result.ok ? "" : result.remaining }])}>
              <Plus className="h-4 w-4" />
              تقسيم الدفع على طريقة أخرى
            </Button>
          ) : null}

          <div className={cn("num flex items-center justify-between rounded-xl border p-3 text-sm font-bold", result.ok ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-800")}>
            <span>{result.ok ? (Number(result.change) > 0 ? "الباقي للعميل" : "المبلغ مطابق") : gap < 0 ? "المتبقي على العميل" : "تعذّر الإتمام"}</span>
            <span>{result.ok ? fmtMoney(Number(result.change)) : gap < 0 ? fmtMoney(Math.abs(gap)) : "—"}</span>
          </div>
          {!result.ok && gap >= 0 && result.reason ? <p role="alert" className="text-xs font-semibold text-rose-600">{result.reason}</p> : null}
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              رجوع للفاتورة
            </Button>
            <Button className="h-9 flex-1 font-bold" disabled={!result.ok || pending} onClick={() => onConfirm(rows)}>
              {pending ? "جارٍ إتمام البيع…" : "تأكيد البيع وطباعة الفاتورة"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
