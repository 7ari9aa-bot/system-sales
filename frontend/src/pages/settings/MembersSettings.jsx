import React from "react";
import { UserPlus, MoreHorizontal } from "lucide-react";
import { useT } from "@/lib/i18n";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

const MEMBERS = [
  { name: "Ahmed Hassan", email: "ahmed@cedarandco.com", role: "owner", status: "active", last: "Now" },
  { name: "Sara Kamel", email: "sara@cedarandco.com", role: "admin", status: "active", last: "2h ago" },
  { name: "Omar Nabil", email: "omar@cedarandco.com", role: "manager", status: "active", last: "1d ago" },
  { name: "Mona Adel", email: "mona@cedarandco.com", role: "staff", status: "invited", last: "—" },
];

const ROLE_TONE = { owner: "primary", admin: "accent", manager: "warning", staff: "muted" };

export default function MembersSettings() {
  const t = useT();
  return (
    <SettingsShell
      title={t("settings.members")}
      subtitle={t("settings.members.desc")}
      actions={
        <Button className="gap-1.5">
          <UserPlus className="h-4 w-4" />
          {t("members.invite")}
        </Button>
      }
    >
      <SettingCard>
        <div className="overflow-x-auto -mx-5 px-5">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                <th className="py-2.5 font-medium">{t("members.name")}</th>
                <th className="py-2.5 font-medium hidden sm:table-cell">{t("members.role")}</th>
                <th className="py-2.5 font-medium hidden md:table-cell">{t("members.status")}</th>
                <th className="py-2.5 font-medium hidden lg:table-cell">{t("members.lastActive")}</th>
                <th className="py-2.5 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {MEMBERS.map((m) => (
                <tr key={m.email} className="border-b border-border last:border-0">
                  <td className="py-3">
                    <div className="flex items-center gap-2.5">
                      <span className="h-8 w-8 rounded-full bg-accent/15 text-accent grid place-items-center text-[11px] font-semibold">
                        {m.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[13px] font-medium truncate">{m.name}</div>
                        <div className="text-[11.5px] text-muted-foreground truncate">{m.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-3 hidden sm:table-cell">
                    <Badge tone={ROLE_TONE[m.role]}>{t(`members.role.${m.role}`)}</Badge>
                  </td>
                  <td className="py-3 hidden md:table-cell">
                    <span className="text-[12.5px] text-muted-foreground capitalize">{m.status}</span>
                  </td>
                  <td className="py-3 hidden lg:table-cell text-[12.5px] text-muted-foreground">{m.last}</td>
                  <td className="py-3 text-right">
                    <button className="h-7 w-7 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground">
                      <MoreHorizontal className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SettingCard>
    </SettingsShell>
  );
}