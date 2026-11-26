import React from "react";
import { Laptop, LogOut, Loader2, ShieldAlert, Smartphone } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";

/** Which devices are signed in to this account, and how to close them.

 * The server decides the list: it reads the live refresh-token chains and marks
 * the one that asked. Nothing here is inferred from the browser — a screen that
 * guesses which sessions exist is worse than no screen, because it invites
 * someone to "sign out" a device that was never there.

 * Three actions, in rising order of consequence: close one device, close every
 * other device, close everything (which signs this one out too and needs the
 * caller to know that before clicking).
 */
function formatMoment(value, lang) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function DeviceIcon({ device }) {
  const mobile = /iPhone|Android|iPad/i.test(device || "");
  const Icon = mobile ? Smartphone : Laptop;
  return <Icon className="h-4 w-4 text-muted-foreground" />;
}

export default function SignedInDevicesCard({
  devices,
  busy,
  error,
  notice,
  onRevoke,
  onRevokeOthers,
  onRevokeAll,
}) {
  const t = useT();
  const { lang } = useI18n();
  const list = Array.isArray(devices) ? devices : null;
  const others = (list || []).filter((device) => !device.current).length;

  return (
    <SettingCard title={t("security.devices.title")} desc={t("security.devices.desc")}>
      {error && (
        <div role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="mt-3 rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">
          {notice}
        </div>
      )}

      {list == null ? (
        <p className="py-3 text-[12.5px] text-muted-foreground" data-testid="devices-loading">
          {t("security.devices.loading")}
        </p>
      ) : list.length === 0 ? (
        <p className="py-3 text-[12.5px] text-muted-foreground" data-testid="devices-empty">
          {t("security.devices.empty")}
        </p>
      ) : (
        <div data-testid="devices-list">
          {list.map((device, index) => (
            <SettingRow
              key={device.id}
              label={
                <span className="flex items-center gap-2">
                  <DeviceIcon device={device.device} />
                  <span>{device.device}</span>
                  {device.current && <Badge tone="success">{t("security.devices.current")}</Badge>}
                </span>
              }
              desc={
                <span className="block space-y-0.5">
                  <span className="block font-mono text-[11.5px]" dir="ltr">
                    {device.ip || "—"}
                  </span>
                  <span className="block">
                    {t("security.devices.signedIn", { date: formatMoment(device.signed_in_at, lang) })}
                  </span>
                </span>
              }
              last={index === list.length - 1}
            >
              {!device.current && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => onRevoke?.(device)}
                  data-testid={`device-revoke-${device.id}`}
                  className="gap-1.5"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  {t("security.devices.revoke")}
                </Button>
              )}
            </SettingRow>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || !others}
          onClick={() => onRevokeOthers?.()}
          data-testid="devices-revoke-others"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {t("security.devices.revokeOthers")}
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={busy || !list || list.length === 0}
          onClick={() => onRevokeAll?.()}
          data-testid="devices-revoke-all"
          className="gap-1.5"
        >
          <ShieldAlert className="h-3.5 w-3.5" />
          {t("security.devices.revokeAll")}
        </Button>
        <span className="text-[11.5px] text-muted-foreground">{t("security.devices.revokeAll.hint")}</span>
      </div>
    </SettingCard>
  );
}
