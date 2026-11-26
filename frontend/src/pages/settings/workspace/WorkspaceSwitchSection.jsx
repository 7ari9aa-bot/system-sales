import React from "react";
import { useNavigate } from "react-router-dom";
import { Check, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";

/** Every workspace this person belongs to, and the way into another one.
 *
 * Switching is a real session change (`POST /auth/switch-tenant`): it issues a new
 * token pair for the other workspace, so the app is reloaded into it rather than
 * pretending a different tenant's data is this one's. A workspace that is not
 * operational is listed but not enterable — the server refuses it, so the button is
 * disabled here instead of failing after the click.
 */
export default function WorkspaceSwitchSection() {
  const t = useT();
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const currentId = activeTenantId(user);

  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState("");
  const [switching, setSwitching] = React.useState("");

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

  async function enter(workspace) {
    if (switching || workspace.id === currentId) return;
    setSwitching(workspace.id);
    setError("");
    try {
      await api("/auth/switch-tenant", { method: "POST", body: { tenant_id: workspace.id } });
      await refreshUser();
      navigate("/dashboard");
    } catch (failure) {
      setError(failure?.message || t("workspace.switch.failed"));
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
      <p className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{t("workspace.switch.note")}</p>
    </SettingsShell>
  );
}
