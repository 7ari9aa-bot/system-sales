import { useState } from "react";
import { useTenantUsers } from "@/applications/apparel/api/useTenantUsers";
import { Button } from "@/applications/apparel/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/applications/apparel/components/ui/dialog";
import { useT } from "@/lib/i18n";

export default function ShiftHandoverDialog({
  open,
  onOpenChange,
  currentCashierId,
  expectedCash = null,
  drawerOn = false,
  pending = false,
  error = null,
  onConfirm,
}) {
  const t = useT();
  const { data: users = [], isLoading } = useTenantUsers();
  const [selectedUserId, setSelectedUserId] = useState("");
  const [counted, setCounted] = useState("");
  const [reason, setReason] = useState("");
  // A drawer that takes payments cannot change hands uncounted: the shortage would belong to
  // whoever holds it last.
  const needsCount = drawerOn && counted.trim() === "";

  const eligibleUsers = users.filter((u) => u.id !== currentCashierId);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!selectedUserId || needsCount) return;
    onConfirm({
      newCashierId: selectedUserId,
      countedCash: drawerOn ? counted.trim() : undefined,
      varianceReason: drawerOn ? reason.trim() : undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{t("pos.handover.title")}</DialogTitle>
          <DialogDescription>
            {t("pos.handover.desc")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="block text-xs font-semibold mb-1 text-slate-700 dark:text-slate-200">
              {t("pos.handover.newCashier")}
            </label>
            {isLoading ? (
              <p className="text-sm text-slate-500">جارٍ التحميل…</p>
            ) : (
              <select
                className="w-full h-10 px-3 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm"
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
                required
              >
                <option value="">{t("pos.handover.selectCashier")}</option>
                {eligibleUsers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.role || "staff"})
                  </option>
                ))}
              </select>
            )}
          </div>

          {drawerOn ? (
            <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <p className="text-xs text-slate-600 dark:text-slate-300">
                {t("pos.handover.expected")}: <b className="num">{expectedCash ?? "—"}</b>
              </p>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-200" htmlFor="handover-counted">
                {t("pos.handover.counted")}
              </label>
              <input
                id="handover-counted"
                dir="ltr"
                inputMode="decimal"
                className="num h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900"
                value={counted}
                onChange={(e) => setCounted(e.target.value)}
                required
              />
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-200" htmlFor="handover-reason">
                {t("pos.handover.reason")}
              </label>
              <input
                id="handover-reason"
                className="h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="مطلوب لو فيه فرق"
              />
              {needsCount ? (
                <p className="text-[11px] font-semibold text-amber-700">{t("pos.handover.countFirst")}</p>
              ) : null}
            </div>
          ) : null}

          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

          <div className="flex gap-2 pt-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              إلغاء
            </Button>
            <Button type="submit" className="flex-1 font-bold" disabled={pending || !selectedUserId || needsCount}>
              {pending ? "جارٍ التسليم…" : t("pos.handover.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
