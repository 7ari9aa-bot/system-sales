import React, { useState } from "react";
import { AlertTriangle, Archive, Trash2, Download } from "lucide-react";
import { useT } from "@/lib/i18n";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function DangerZoneSettings() {
  const t = useT();
  const [open, setOpen] = useState(false);

  return (
    <SettingsShell title={t("settings.dangerZone")} subtitle={t("settings.dangerZone.desc")}>
      <SettingCard>
        <div className="divide-y divide-border">
          <Row icon={Download} title={t("danger.export")} desc={t("danger.export.desc")}>
            <Button variant="outline" className="h-8 text-[12.5px]">{t("danger.export")}</Button>
          </Row>
          <Row icon={Archive} title={t("danger.archive")} desc={t("danger.archive.desc")}>
            <Button variant="outline" className="h-8 text-[12.5px]">{t("danger.archive")}</Button>
          </Row>
          <Row icon={Trash2} title={t("danger.delete")} desc={t("danger.delete.desc")} danger>
            <AlertDialog open={open} onOpenChange={setOpen}>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" className="h-8 text-[12.5px]">{t("danger.delete")}</Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-destructive" />
                    {t("danger.delete")}
                  </AlertDialogTitle>
                  <AlertDialogDescription>{t("danger.delete.desc")}</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("ls.cancel")}</AlertDialogCancel>
                  <AlertDialogAction className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    {t("danger.delete")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </Row>
        </div>
      </SettingCard>
    </SettingsShell>
  );
}

function Row({ icon: Icon, title, desc, children, danger }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 py-4 first:pt-1 last:pb-1">
      <div className="flex items-start gap-3 min-w-0">
        <span className={`h-9 w-9 rounded-lg grid place-items-center shrink-0 ${danger ? "bg-destructive/10 text-destructive" : "bg-surface border border-border text-muted-foreground"}`}>
          <Icon className="h-4 w-4" />
        </span>
        <div>
          <div className="text-[13.5px] font-medium">{title}</div>
          <div className="text-[12px] text-muted-foreground mt-0.5">{desc}</div>
        </div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}