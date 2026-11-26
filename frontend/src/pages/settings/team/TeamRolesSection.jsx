import React from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";

/** The roles that exist, and the permissions each one actually carries.
 *
 * Read-only, and deliberately so: the four roles are seeded by the platform and the
 * guards in the API are written against their codes. A page that could rewrite a
 * role's permission set would let a workspace grant an action the server does not
 * expect to exist, which is the one kind of "flexible" that breaks a product.
 */
export default function TeamRolesSection() {
  const t = useT();
  const [matrix, setMatrix] = React.useState(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api("/roles/matrix")
      .then((data) => {
        if (alive) setMatrix(data);
      })
      .catch((failure) => {
        if (alive) setError(failure?.message || "failed");
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <SettingsShell title={t("team.roles.title")} desc={t("team.roles.desc")}>
      {error && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {t("team.loadFailed")}
        </div>
      )}
      {!matrix && !error && (
        <p className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("team.loading")}
        </p>
      )}
      {matrix && (
        <SettingCard title={t("team.roles.list")} desc={t("team.roles.list.desc")}>
          {matrix.roles.map((role, index) => (
            <SettingRow
              key={role.code}
              label={t(`members.role.${role.code}`)}
              desc={role.description || role.code}
              last={index === matrix.roles.length - 1}
            >
              <span className="text-[12px] font-medium tabular-nums text-muted-foreground">
                {t("team.roles.count", { count: role.permissions.length })}
              </span>
            </SettingRow>
          ))}
        </SettingCard>
      )}
      <div className="mt-4 flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-[11.5px] leading-relaxed">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <span>{t("team.roles.readOnly")}</span>
      </div>
    </SettingsShell>
  );
}
