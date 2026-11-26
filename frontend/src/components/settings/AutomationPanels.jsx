/** Section 15's one non-list surface: the execution attempts of every workflow.
 *
 * The automation module keeps workflows, workflow_versions, workflow_executions and
 * workflow_failures, and an execution is per workflow (`GET /automation/{id}/executions`), so this
 * panel lists the workflows first and then reads each one's attempts. It shows the error text the
 * engine stored, because "it failed" without the reason is not an attempt record.
 */
import React from "react";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { Badge } from "@/components/dashboard/ui";
import { SettingCard } from "@/components/settings/SettingsShell";

const MAX_WORKFLOWS = 10;

export default function ExecutionsPanel() {
  const t = useT();
  const [state, setState] = React.useState({ loading: true, groups: [], error: "" });

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api("/automation");
        const workflows = (Array.isArray(res) ? res : (res?.items ?? [])).slice(0, MAX_WORKFLOWS);
        const groups = await Promise.all(
          workflows.map(async (w) => {
            try {
              const runs = await api(`/automation/${w.id}/executions`);
              return { workflow: w, runs: Array.isArray(runs) ? runs : (runs?.items ?? []) };
            } catch {
              return { workflow: w, runs: [] };
            }
          }),
        );
        if (alive) setState({ loading: false, groups, error: "" });
      } catch (e) {
        if (alive) setState({ loading: false, groups: [], error: e?.message || "" });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <SettingCard
      title={t("settings.automation.executions.title")}
      desc={t("settings.automation.executions.desc")}
    >
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.automation.executions.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.automation.executions.loadError")}
        </p>
      ) : state.groups.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {t("settings.automation.executions.empty")}
        </p>
      ) : (
        <div className="space-y-4">
          {state.groups.map(({ workflow, runs }) => (
            <div key={workflow.id}>
              <p className="text-[13px] font-medium">{workflow.name}</p>
              {runs.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">
                  {t("settings.automation.executions.none")}
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {runs.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center gap-2 py-1.5 text-[12px]">
                      <Badge tone="muted">{r.status}</Badge>
                      <span className="num text-muted-foreground">
                        v{r.workflow_version} · {r.started_at || "—"}
                      </span>
                      {r.error ? <span className="text-destructive">{r.error}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="mt-3 text-[12px] text-muted-foreground">
        {t("settings.automation.executions.whereToEdit")}
      </p>
    </SettingCard>
  );
}
