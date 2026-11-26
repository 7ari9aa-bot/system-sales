import React from "react";
import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";
import { useT } from "@/lib/i18n";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";

/** Closing the account, and the handover that has to happen before it.

 * Three states, all decided by the server: a request is open (show it, allow
 * withdrawing it), the person owns a shop alone (say WHICH shop and stop), or
 * nothing is in the way (offer the form). The card never guesses: an unknown
 * state renders the loading line instead of a form that would fail.
 */
export default function AccountClosureCard({ state, busy, error, notice, onOpen, onCancel }) {
  const t = useT();
  const [mode, setMode] = React.useState("close");
  const [reason, setReason] = React.useState("");

  const request = state?.request || null;
  const blockers = state?.blockers || [];
  const open = request && request.status === "pending";

  function submit(event) {
    event.preventDefault();
    if (busy) return;
    onOpen?.(mode, reason.trim() || null);
  }

  return (
    <SettingCard title={t("account.closure.title")} desc={t("account.closure.desc")}>
      <div className="space-y-3 pt-1">
        <p className="text-[12.5px] text-muted-foreground">
          {t("account.closure.memberships", { count: state?.memberships ?? 0 })}
        </p>

        {error && (
          <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}
        {notice && (
          <div role="status" className="rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">
            {notice}
          </div>
        )}

        {state == null ? (
          <p className="text-[12.5px] text-muted-foreground" data-testid="closure-loading">
            {t("account.closure.loading")}
          </p>
        ) : open ? (
          <div className="space-y-2" data-testid="closure-pending">
            <div className="flex items-center gap-2">
              <Badge tone="warning">{t("account.closure.status.pending")}</Badge>
              <span className="text-[12.5px] text-muted-foreground">
                {request.mode === "delete"
                  ? t("account.closure.mode.delete")
                  : t("account.closure.mode.close")}
              </span>
            </div>
            <p className="text-[12.5px] text-muted-foreground">{t("account.closure.pending")}</p>
            {request.created_at && (
              <p className="text-[12px] text-muted-foreground" dir="ltr">
                {t("account.closure.pending.since", {
                  date: String(request.created_at).slice(0, 10),
                })}
              </p>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onCancel?.()}
              data-testid="closure-withdraw"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("account.closure.withdraw")}
            </Button>
          </div>
        ) : blockers.length > 0 ? (
          <div className="space-y-2" data-testid="closure-blocked">
            <div className="flex items-start gap-2">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              <div className="min-w-0">
                <div className="text-[13px] font-medium">{t("account.closure.blocked.title")}</div>
                <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                  {t("account.closure.blocked.desc")}
                </p>
              </div>
            </div>
            <ul className="ms-6 list-disc text-[12.5px] text-foreground">
              {blockers.map((blocker) => (
                <li key={blocker.tenant_id} data-testid="closure-blocker">
                  {blocker.tenant_name}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3" data-testid="closure-form">
            <fieldset className="space-y-2">
              <legend className="text-[12.5px] font-medium">{t("account.closure.mode")}</legend>
              {[
                { value: "close", label: t("account.closure.mode.close"), impact: t("account.closure.impact.close") },
                { value: "delete", label: t("account.closure.mode.delete"), impact: t("account.closure.impact.delete") },
              ].map((option) => (
                <label
                  key={option.value}
                  className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 ${
                    mode === option.value ? "border-primary bg-primary/5" : "border-border"
                  }`}
                >
                  <input
                    type="radio"
                    name="closure-mode"
                    value={option.value}
                    checked={mode === option.value}
                    onChange={() => setMode(option.value)}
                    className="mt-1"
                  />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{option.label}</span>
                    <span className="mt-0.5 block text-[12px] text-muted-foreground">{option.impact}</span>
                  </span>
                </label>
              ))}
            </fieldset>

            <label className="grid gap-1.5 text-[12.5px] text-muted-foreground">
              {t("account.closure.reason")}
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={1000}
                rows={3}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-[13px] text-foreground"
                data-testid="closure-reason"
              />
            </label>

            <div className="flex items-start gap-2 text-[12px] text-muted-foreground">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              <span>{t("account.closure.desc")}</span>
            </div>

            <Button type="submit" variant="destructive" disabled={busy} data-testid="closure-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("account.closure.submit")}
            </Button>
          </form>
        )}

        {!open && request && (
          <p className="text-[12px] text-muted-foreground" data-testid="closure-decided">
            {t("account.closure.decided", {
              status: t(`account.closure.status.${request.status}`, request.status),
            })}
          </p>
        )}
      </div>
    </SettingCard>
  );
}
