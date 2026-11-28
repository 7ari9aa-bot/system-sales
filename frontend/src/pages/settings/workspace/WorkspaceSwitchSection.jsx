import React from "react";
import { useNavigate } from "react-router-dom";
import { Check, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api, getWorkspaceScope, invalidateCache, setWorkspaceScope } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";

/** Every workspace this person belongs to, and the way into another one.
 *
 * Switching is NOT a session change. It used to post the workspace id to
 * `/auth/switch-tenant`, which swapped the ACCOUNT — so a shop owner with two
 * businesses was signing out of one company into another, and the audit called
 * that out. A workspace is a business inside the account, so entering one sets
 * the scope the API client already sends (`X-Workspace-Id`) and drops the cached
 * data of the business being left behind. The account, the plan and the session
 * stay exactly as they were.
 *
 * A workspace that is not operational is listed but not enterable — the server
 * refuses it in `resolve_scope`, so the button is disabled here instead of
 * failing after the click.
 */
export default function WorkspaceSwitchSection() {
  const t = useT();
  const navigate = useNavigate();
  const { user } = useAuth();
  // The business being viewed is the scope the client sends, not the account:
  // comparing against the tenant id marked every row "current" in a one-workspace
  // account and none of them in a multi-workspace one.
  const currentId = getWorkspaceScope()?.workspaceId || activeTenantId(user);

  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState("");
  const [switching, setSwitching] = React.useState("");
  // What this business actually has, asked of the server: only it knows what was
  // paid for and how far each setup got, so the screen never guesses from a list.
  const [apps, setApps] = React.useState(null);
  const [appsError, setAppsError] = React.useState("");
  const [installing, setInstalling] = React.useState(false);
  const [installed, setInstalled] = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    api("/workspaces")
      .then((data) => {
        if (alive) setRows(data || []);
      })
      .catch((failure) => {
        if (alive) setError(failure?.message || "failed");
      });
    return () => {
      alive = false;
    };
  }, []);

  const loadApps = React.useCallback(() => {
    return api("/applications")
      .then((data) => {
        setApps(data?.applications || []);
        return data;
      })
      .catch((failure) => {
        setAppsError(failure?.message || "failed");
        return null;
      });
  }, []);

  React.useEffect(() => {
    loadApps();
  }, [loadApps]);

  /** Record what this business is licensed for, then read the verdict again.
   *  A business that finished setup before the installations table existed has
   *  no rows, so the gate has to let it through as "not configured yet" - this
   *  button closes that window for this business, and only for it: the server
   *  takes the workspace from the session, not from this request. */
  async function recordApplications() {
    if (installing) return;
    setInstalling(true);
    setAppsError("");
    setInstalled(null);
    try {
      const result = await api("/applications/install", { method: "POST", body: {} });
      setInstalled(result?.installed || []);
      await loadApps();
    } catch (failure) {
      setAppsError(failure?.message || t("workspace.apps.install.failed"));
    } finally {
      setInstalling(false);
    }
  }

  async function enter(workspace) {
    if (switching || workspace.id === currentId) return;
    setSwitching(workspace.id);
    setError("");
    try {
      // The scope the client sends, not a different account: the server checks
      // the membership row on the next request and answers 403 if there is none.
      setWorkspaceScope({ workspaceId: workspace.id, locationId: null });
      invalidateCache();
      navigate("/dashboard");
    } catch (failure) {
      setError(failure?.message || t("workspace.switch.failed"));
    } finally {
      setSwitching("");
    }
  }

  return (
    <SettingsShell title={t("workspace.switch.title")} subtitle={t("workspace.switch.desc")}>
      <SettingCard title={t("workspace.switch.list")} desc={t("workspace.switch.list.desc")}>
        {error && (
          <div role="alert" className="mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}
        {rows === null && !error && (
          <p className="inline-flex items-center gap-2 py-2 text-[12.5px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("workspace.loading")}
          </p>
        )}
        {(rows || []).map((workspace, index) => {
          const isCurrent = workspace.id === currentId;
          const enterable = workspace.is_active && workspace.lifecycle_state !== "suspended";
          return (
            <SettingRow
              key={workspace.id}
              label={workspace.name}
              desc={`${workspace.slug} · ${t(`workspace.role.${workspace.role_code || "member"}`)}`}
              last={index === (rows || []).length - 1}
            >
              {isCurrent ? (
                <span
                  className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground"
                  data-testid={`workspace-current-${workspace.slug}`}
                >
                  <Check className="h-4 w-4" />
                  {t("workspace.switch.current")}
                </span>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!enterable || Boolean(switching)}
                  onClick={() => enter(workspace)}
                  data-testid={`workspace-enter-${workspace.slug}`}
                  title={enterable ? undefined : t("workspace.switch.unavailable")}
                >
                  {switching === workspace.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    t("workspace.switch.enter")
                  )}
                </Button>
              )}
            </SettingRow>
          );
        })}
      </SettingCard>
      <div className="mt-4">
        <SettingCard title={t("workspace.apps.title")} desc={t("workspace.apps.desc")}>
          {appsError && (
            <div role="alert" className="mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
              {appsError}
            </div>
          )}
          {apps === null && !appsError && (
            <p className="inline-flex items-center gap-2 py-2 text-[12.5px] text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("workspace.apps.loading")}
            </p>
          )}
          {apps !== null && apps.length === 0 && (
            <p className="py-2 text-[12.5px] text-muted-foreground">{t("workspace.apps.empty")}</p>
          )}
          {(apps || []).map((application, index) => {
            const reason = String(application.reason || "");
            const base = reason.split(":")[0];
            return (
              <SettingRow
                key={application.key}
                label={application.title_ar || application.title_en || application.key}
                desc={t(`workspace.apps.reason.${base}`) === `workspace.apps.reason.${base}`
                  ? reason
                  : t(`workspace.apps.reason.${base}`)}
                last={index === (apps || []).length - 1}
              >
                {application.allowed ? (
                  <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-emerald-600">
                    <Check className="h-4 w-4" />
                    {t("workspace.apps.reason.allowed")}
                  </span>
                ) : (
                  <span className="text-[12px] text-muted-foreground">{application.key}</span>
                )}
              </SettingRow>
            );
          })}
          {installed !== null && (
            <p className="mt-2 text-[12px] text-emerald-600" data-testid="applications-installed">
              {t("workspace.apps.installed")}
              {installed.length ? installed.join("، ") : "—"}
            </p>
          )}
          <div className="mt-3 border-t pt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={installing}
              onClick={recordApplications}
              data-testid="applications-install"
            >
              {installing ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  {t("workspace.apps.installing")}
                </>
              ) : (
                t("workspace.apps.install")
              )}
            </Button>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
              {t("workspace.apps.install.hint")}
            </p>
          </div>
        </SettingCard>
      </div>
      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("workspace.switch.note")}</p>
    </SettingsShell>
  );
}
