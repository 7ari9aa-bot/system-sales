import React from "react";
import { useT } from "@/lib/i18n";
import { useRealChannels } from "@/hooks/useRealData";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

export default function ChannelsSettings() {
  const t = useT();
  return (
    <SettingsShell title={t("channels.title")} subtitle={t("channels.subtitle")}>
      <SettingCard>
        <div className="divide-y divide-border">
          {channels.map((c) => {
            const needsAttention = c.id === "instagram";
            return (
              <div key={c.id} className="flex items-center gap-3 py-3.5 first:pt-1 last:pb-1">
                <ChannelIcon channel={c.id} />
                <div className="flex-1 min-w-0">
                  <div className="text-[13.5px] font-medium">{t(`channel.${c.id}`)}</div>
                  <div className="text-[12px] text-muted-foreground">
                    {needsAttention ? t("channels.needsAttention") : c.connected ? t("channels.connected") : t("channels.notConnected")}
                  </div>
                </div>
                {needsAttention ? (
                  <Button variant="outline" className="h-8 text-[12.5px]">{t("channels.reconnect")}</Button>
                ) : c.connected ? (
                  <>
                    <Badge tone="success">{t("channels.connected")}</Badge>
                    <Button variant="ghost" className="h-8 text-[12.5px]">{t("channels.manage")}</Button>
                  </>
                ) : (
                  <Button variant="outline" className="h-8 text-[12.5px]">{t("channels.connect")}</Button>
                )}
              </div>
            );
          })}
        </div>
      </SettingCard>
    </SettingsShell>
  );
}