import React from "react";
import { useI18n, useT } from "@/lib/i18n";
import { useRealChannels } from "@/hooks/useRealData";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Badge } from "@/components/dashboard/ui";

export default function ChannelsSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { channels, loading, error } = useRealChannels();
  const isAr = lang === "ar";

  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      <SettingCard>
        {error && <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
        {loading && channels.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل القنوات…" : "Loading channels…"}</div>
        ) : (
          <div className="divide-y divide-border">
            {channels.map((channel) => {
              const status = channel.status || "not_connected";
              const connected = channel.connected;
              const needsAttention = ["reauth_required", "degraded", "error"].includes(status);
              const statusLabel = needsAttention
                ? t("channels.needsAttention")
                : connected
                  ? t("channels.connected")
                  : t("channels.notConnected");
              return (
                <div key={channel.id} className="flex items-center gap-3 py-3.5 first:pt-1 last:pb-1">
                  <ChannelIcon channel={channel.id} />
                  <div className="flex-1 min-w-0">
                    <div className="text-[13.5px] font-medium">{t(`channel.${channel.id}`)}</div>
                    <div className="text-[12px] text-muted-foreground">{statusLabel}</div>
                  </div>
                  <Badge tone={connected ? "success" : needsAttention ? "warning" : "muted"}>{statusLabel}</Badge>
                </div>
              );
            })}
          </div>
        )}
        <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
          {isAr
            ? "إجراءات ربط القنوات وإعادة المصادقة غير متاحة عبر الواجهة الحالية. الحالات المعروضة مأخوذة مباشرة من تكاملات مساحة العمل."
            : "Channel connection and reauthentication actions are not available in the current API. The statuses shown come directly from this workspace’s integrations."}
        </p>
      </SettingCard>
    </SettingsShell>
  );
}
