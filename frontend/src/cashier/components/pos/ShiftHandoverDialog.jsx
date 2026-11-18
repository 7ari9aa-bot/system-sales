import { useState } from "react";
import { useTenantUsers } from "@/cashier/api/useTenantUsers";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { useT } from "@/lib/i18n";

export default function ShiftHandoverDialog({ open, onOpenChange, currentCashierId, pending = false, error = null, onConfirm }) {
  const t = useT();
  const { data: users = [], isLoading } = useTenantUsers();
  const [selectedUserId, setSelectedUserId] = useState("");

  const eligibleUsers = users.filter((u) => u.id !== currentCashierId);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!selectedUserId) return;
    onConfirm(selectedUserId);
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

          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}

          <div className="flex gap-2 pt-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              إلغاء
            </Button>
            <Button type="submit" className="flex-1 font-bold" disabled={pending || !selectedUserId}>
              {pending ? "جارٍ التسليم…" : t("pos.handover.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
