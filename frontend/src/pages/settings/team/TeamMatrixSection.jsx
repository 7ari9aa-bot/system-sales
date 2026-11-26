import React from "react";
import { Check, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";

/** The matrix: every permission the server enforces, against every role that holds it.
 *
 * Two decisions worth stating. The rows are the REAL permissions table, grouped by
 * resource, so a cell can only be ticked for something the API checks. And the three
 * actions are shown as read / write / approve in their own words, because "orders:read"
 * and "orders:approve" are not two shades of the same permission — one looks, one
 * commits, and an approval is what a high-risk setting needs.
 *
 * Editing is not offered: see TeamRolesSection for why.
 */
const ACTION_ORDER = ["read", "write", "approve", "manage", "delete", "execute"];

export default function TeamMatrixSection() {
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

  const rows = React.useMemo(() => {
    if (!matrix) return [];
    const byResource = new Map();
    for (const permission of matrix.permissions) {
      if (!byResource.has(permission.resource)) byResource.set(permission.resource, []);
      byResource.get(permission.resource).push(permission);
    }
    return [...byResource.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([resource, permissions]) => ({
        resource,
        permissions: permissions.sort(
          (a, b) =>
            (ACTION_ORDER.indexOf(a.action) + 1 || 99) - (ACTION_ORDER.indexOf(b.action) + 1 || 99),
        ),
      }));
  }, [matrix]);

  const held = React.useMemo(() => {
    const set = new Set();
    for (const role of matrix?.roles || []) {
      for (const code of role.permissions) set.add(`${role.code}:${code}`);
    }
    return set;
  }, [matrix]);

  return (
    <SettingsShell title={t("team.matrix.title")} desc={t("team.matrix.desc")}>
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
        <SettingCard title={t("team.matrix.table")} desc={t("team.matrix.table.desc")}>
          <div className="overflow-x-auto pt-2">
            <table className="w-full text-start" data-testid="permission-matrix">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 font-medium">{t("team.matrix.permission")}</th>
                  {matrix.roles.map((role) => (
                    <th key={role.code} className="py-2 px-2 text-center font-medium whitespace-nowrap">
                      {t(`members.role.${role.code}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((group) => (
                  <React.Fragment key={group.resource}>
                    <tr className="bg-muted/40">
                      <td colSpan={matrix.roles.length + 1} className="py-1.5 text-[11.5px] font-semibold">
                        {t(`team.resource.${group.resource}`, group.resource)}
                      </td>
                    </tr>
                    {group.permissions.map((permission) => (
                      <tr key={permission.code} className="border-b border-border last:border-0">
                        <td className="py-2 text-[12.5px]" dir="ltr">
                          <span className="text-muted-foreground">{permission.resource}:</span>
                          <span className="font-medium">{permission.action}</span>
                          <span className="ms-2 text-[11px] text-muted-foreground">
                            {t(`team.action.${permission.action}`, permission.action)}
                          </span>
                        </td>
                        {matrix.roles.map((role) => (
                          <td key={role.code} className="py-2 px-2 text-center">
                            {held.has(`${role.code}:${permission.code}`) ? (
                              <Check
                                className="mx-auto h-4 w-4 text-primary"
                                aria-label={t("team.matrix.granted")}
                              />
                            ) : (
                              <span className="text-muted-foreground" aria-hidden="true">
                                ·
                              </span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </SettingCard>
      )}
      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("team.matrix.note")}</p>
    </SettingsShell>
  );
}
