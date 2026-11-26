import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Building2, ShieldCheck, Users } from "lucide-react";
import { useT } from "@/lib/i18n";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import useWorkspace from "./useWorkspace";

/** What this container is, what state it is in, and your own place in it.
 *
 * The page says out loud that a workspace is not the store, because the two are
 * easy to conflate and the difference decides where a setting belongs: a currency
 * is the business's, a member's role is the workspace's.
 */
const LINKS = [
  { to: "/settings/workspace/data", icon: Building2, labelKey: "workspace.overview.link.data" },
  { to: "/settings/workspace/ownership", icon: ShieldCheck, labelKey: "workspace.overview.link.ownership" },
  { to: "/settings/workspace/switch", icon: Users, labelKey: "workspace.overview.link.switch" },
];

export default function WorkspaceOverviewSection() {
  const t = useT();
  const { data, error, loading } = useWorkspace();

  return (
    <SettingsShell title={t("workspace.overview.title")} subtitle={t("workspace.overview.desc")}>
      {error && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {t("workspace.loadFailed")}
        </div>
      )}
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("workspace.overview.identity")} desc={t("workspace.overview.identity.desc")}>
          <SettingRow label={t("workspace.name")}>
            <span className="text-[13px] font-medium" data-testid="workspace-overview-name">
              {loading ? "…" : data?.name || "—"}
            </span>
          </SettingRow>
          <SettingRow label={t("workspace.slug")} desc={t("workspace.slug.desc")}>
            <span className="text-[13px] font-medium text-muted-foreground bdi" dir="ltr">
              {data?.slug || "—"}
            </span>
          </SettingRow>
          <SettingRow label={t("workspace.role")}>
            <span className="text-[13px] font-medium">
              {data?.role_code ? t(`workspace.role.${data.role_code}`) : "—"}
            </span>
          </SettingRow>
          <SettingRow label={t("workspace.overview.members")} last>
            <span className="text-[13px] font-medium tabular-nums">{data?.member_count ?? "—"}</span>
          </SettingRow>
        </SettingCard>

        <SettingCard title={t("workspace.overview.state")} desc={t("workspace.overview.state.desc")}>
          <SettingRow label={t("workspace.state")}>
            <span
              className="text-[13px] font-medium"
              data-testid="workspace-overview-state"
            >
              {data ? t(`workspace.state.${data.lifecycle_state}`) : "—"}
            </span>
          </SettingRow>
          {data?.status_reason && (
            <SettingRow label={t("workspace.statusReason")} desc={data.status_reason}>
              <span className="text-[12px] text-muted-foreground">—</span>
            </SettingRow>
          )}
          <SettingRow label={t("regional.currency")}>
            <span className="text-[13px] font-medium bdi">{data?.currency || "—"}</span>
          </SettingRow>
          <SettingRow label={t("regional.timezone")} last>
            <span className="text-[13px] text-muted-foreground">{data?.timezone || t("workspace.overview.zoneDefault")}</span>
          </SettingRow>
        </SettingCard>
      </div>

      <div className="mt-6">
        <SettingCard title={t("workspace.overview.next")} desc={t("workspace.overview.next.desc")}>
          <div className="flex flex-col gap-1 pt-1">
            {LINKS.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className="flex items-center justify-between rounded-lg px-2 py-2 text-[13px] font-medium hover:bg-muted"
                >
                  <span className="inline-flex items-center gap-2">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    {t(item.labelKey)}
                  </span>
                  <ArrowLeft className="h-4 w-4 text-muted-foreground rtl:rotate-0 ltr:rotate-180" />
                </Link>
              );
            })}
          </div>
        </SettingCard>
      </div>

      <p className="mt-6 text-[11.5px] leading-relaxed text-muted-foreground">{t("workspace.overview.note")}</p>
    </SettingsShell>
  );
}
