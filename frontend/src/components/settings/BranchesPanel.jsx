/** The branches themselves, read from the hierarchy the rest of the system already uses.
 *
 * A branch is a `locations` row inside a `workspace` — not a settings key and not a warehouse.
 * This panel lists what exists so the page can talk about the real structure: the settings beside
 * it decide how many branches the shop may have, and this is the answer to "how many do I have".
 */
import React from "react";
import { Loader2, Store } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

export default function BranchesPanel() {
  const t = useT();
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  // [{ workspace, locations: [] }]
  const [groups, setGroups] = React.useState([]);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api("/hierarchy/workspaces");
        const workspaces = Array.isArray(res?.items) ? res.items : [];
        const withLocations = await Promise.all(
          workspaces.map(async (w) => {
            try {
              const locs = await api(`/hierarchy/workspaces/${w.id}/locations`);
              return { workspace: w, locations: Array.isArray(locs?.items) ? locs.items : [] };
            } catch {
              // A workspace we cannot read still counts as a branch the shop has.
              return { workspace: w, locations: [] };
            }
          }),
        );
        if (alive) setGroups(withLocations);
      } catch (e) {
        if (alive) setError(e?.message || t("settings.locations.loadError"));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [t]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.locations.loading")}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="text-[13px] text-destructive">
        {error}
      </div>
    );
  }

  const total = groups.reduce((n, g) => n + g.locations.length, 0);

  return (
    <SettingCard
      title={t("settings.locations.branches.title")}
      desc={t("settings.locations.branches.desc")}
    >
      <div className="flex items-center gap-2 py-2">
        <Badge tone="muted">
          {total} {total === 1 ? t("settings.locations.branchOne") : t("settings.locations.branchMany")}
        </Badge>
        <Badge tone="muted">
          {groups.length}{" "}
          {groups.length === 1
            ? t("settings.locations.workspaceOne")
            : t("settings.locations.workspaceMany")}
        </Badge>
      </div>

      {groups.length === 0 && (
        <p className="py-3 text-[13px] text-muted-foreground">
          {t("settings.locations.branches.empty")}
        </p>
      )}

      {groups.map(({ workspace, locations }) => (
        <div key={workspace.id} className="border-t border-border py-2.5 first:border-t-0">
          <div className="flex items-center gap-2">
            <Store className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="text-[13px] font-medium">{workspace.name}</span>
            <span className="text-[12px] text-muted-foreground">{workspace.slug}</span>
          </div>
          {locations.length === 0 ? (
            <p className="mt-1 ps-5 text-[12.5px] text-muted-foreground">
              {t("settings.locations.branches.noneInWorkspace")}
            </p>
          ) : (
            <ul className="mt-1 space-y-1 ps-5">
              {locations.map((loc) => (
                <li key={loc.id} className="flex items-center gap-2 text-[12.5px]">
                  <span>{loc.name}</span>
                  {loc.code && <span className="num text-muted-foreground">{loc.code}</span>}
                  {!loc.is_active && (
                    <Badge tone="muted">{t("settings.locations.branches.inactive")}</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </SettingCard>
  );
}
