import { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { useTranslation } from "@/lib/i18n";

export default function CashMovementDialog({ open, onOpenChange, pending = false, error = null, onConfirm }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("pay_in");
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!amount || Number(amount) <= 0) return;
    onConfirm({ reason, amount: Number(amount).toFixed(2), notes: notes.trim() || undefined });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{t("pos.cashMovement.title")}</DialogTitle>
          <DialogDescription>
            {t("pos.cashMovement.notes")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="block text-xs font-semibold mb-1 text-slate-700 dark:text-slate-200">
              {t("pos.cashMovement.reason")}
            </label>
            <select
              className="w-full h-10 px-3 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            >
              <option value="pay_in">{t("pos.cashMovement.payIn")}</option>
              <option value="pay_out">{t("pos.cashMovement.payOut")}</option>
              <option value="cash_drop">{t("pos.cashMovement.cashDrop")}</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1 text-slate-700 dark:text-slate-200">
              {t("pos.cashMovement.amount")}
            </label>
            <Input
              type="number"
              step="0.01"
              min="0.01"
              required
              placeholder="0.00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1 text-slate-700 dark:text-slate-200">
              {t("pos.cashMovement.notes")}
            </label>
            <Input
              type="text"
              maxLength={255}
              placeholder="وصف الحركة (اختياري)"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

          <div className="flex gap-2 pt-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              إلغاء
            </Button>
            <Button type="submit" className="flex-1 font-bold" disabled={pending || !amount || Number(amount) <= 0}>
              {pending ? "جارٍ التسجيل…" : t("pos.cashMovement.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
