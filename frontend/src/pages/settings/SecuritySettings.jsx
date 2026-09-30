import React, { useState } from "react";
import { useT } from "@/lib/i18n";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

export default function SecuritySettings() {
  const t = useT();
  const [twoStep, setTwoStep] = useState(false);
  return (
    <SettingsShell title={t("settings.security")} subtitle={t("settings.security.desc")}>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard title={t("ls.auth")}>
          <SettingRow label={t("ls.password")} desc={t("ls.password.d")}>
            <Button variant="outline" className="h-8 text-[12.5px]">{t("ls.change")}</Button>
          </SettingRow>
          <SettingRow label={t("ls.twoStep")} desc={t("ls.twoStep.d")} last>
            <Switch checked={twoStep} onCheckedChange={setTwoStep} />
          </SettingRow>
        </SettingCard>

        <SettingCard title={t("ls.sessions")}>
          <div className="space-y-3 pt-2">
            {[
              { device: "MacBook Pro · Cairo", current: true, time: t("ls.now") },
              { device: "iPhone 15 · Cairo", current: false, time: t("ls.ago2h") },
            ].map((s) => (
              <div key={s.device} className="flex items-center justify-between">
                <div>
                  <div className="text-[13px] font-medium">{s.device}</div>
                  <div className="text-[11.5px] text-muted-foreground">{s.time}</div>
                </div>
                {s.current ? (
                  <Badge tone="success">{t("ls.current")}</Badge>
                ) : (
                  <Button variant="ghost" className="h-8 text-[12.5px] text-destructive">{t("ls.revoke")}</Button>
                )}
              </div>
            ))}
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}