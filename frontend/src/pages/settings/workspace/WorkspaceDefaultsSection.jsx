import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useT } from "@/lib/i18n";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import useWorkspace from "./useWorkspace";

/** What this workspace hands down to everything inside it.
 *
 * Read-only on purpose. Each of these values is editable exactly once, on the page
 * that owns it (region on Workspace data, the assistant's dialect in AI), and this
 * page shows the value that the rest of the product inherits plus a link to the one
 * place it can be changed. A second editable copy here would be the duplicate
 * setting the map forbids: two screens writing the same column, and whichever saved
 * last winning silently.
 */
const INHERITED = [
  {
    key: "currency",
    labelKey: "regional.currency",
    descKey: "workspace.defaults.currency.desc",
    owner: "/settings/workspace/data",
    ownerKey: "workspace.defaults.owner.data",
  },
  {
    key: "timezone",
    labelKey: "regional.timezone",
    descKey: "workspace.defaults.timezone.desc",
    owner: "/settings/workspace/data",
    ownerKey: "workspace.defaults.owner.data",
  },
  {
    key: "country_code",
    labelKey: "workspace.defaults.country",
    descKey: "workspace.defaults.country.desc",
    owner: "/settings/workspace/data",
    ownerKey: "workspace.defaults.owner.data",
  },
  {
    key: "dialect",
    labelKey: "dialect.title",
    descKey: "workspace.defaults.dialect.desc",
    owner: "/settings/ai",
    ownerKey: "workspace.defaults.owner.ai",
  },
];

export default function WorkspaceDefaultsSection() {
  const t = useT();
  const { data, error } = useWorkspace();

  return (
    <SettingsShell title={t("workspace.defaults.title")} subtitle={t("workspace.defaults.desc")}>
      {error && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {t("workspace.loadFailed")}
        </div>
      )}
      <SettingCard title={t("workspace.defaults.inherited")} desc={t("workspace.defaults.inherited.desc")}>
        {INHERITED.map((item, index) => {
          const value = data ? data[item.key] : null;
          return (
            <SettingRow
              key={item.key}
              label={t(item.labelKey)}
              desc={t(item.descKey)}
              last={index === INHERITED.length - 1}
            >
              <div className="flex items-center gap-3">
                <span className="text-[13px] font-medium bdi" dir="ltr" data-testid={`workspace-default-${item.key}`}>
                  {value || t("workspace.defaults.unset")}
                </span>
                <Link
                  to={item.owner}
                  className="inline-flex items-center gap-1 text-[11.5px] font-medium text-primary hover:underline"
                >
                  {t(item.ownerKey)}
                  <ArrowLeft className="h-3 w-3 ltr:rotate-180" />
                </Link>
              </div>
            </SettingRow>
          );
        })}
      </SettingCard>
      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("workspace.defaults.note")}</p>
    </SettingsShell>
  );
}
