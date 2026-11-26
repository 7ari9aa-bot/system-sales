import React from "react";
import { Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import useWorkspace from "./useWorkspace";

/** Who owns this workspace, and who else can administer it.
 *
 * Ownership transfer is NOT offered as a button. Handing over an account moves the
 * one role that cannot walk away from its shop, and there is no transfer endpoint
 * behind a button like that today: the honest page names the owner, lists the
 * admins, and says what a transfer would need. A greyed-out "Transfer" that fails on
 * click is worse than a sentence that tells the truth.
 */
export default function WorkspaceOwnershipSection() {
  const t = useT();
  const { data } = useWorkspace();
  const [state, setState] = React.useState({ admins: null, roster: null, denied: false, error: "", loading: true });

  React.useEffect(() => {
    let alive = true;
    Promise.all([api("/workspaces/current/admins"), api("/users")])
      .then(([admins, roster]) => {
        if (alive) setState({ admins, roster, denied: false, error: "", loading: false });
      })
      .catch((failure) => {
        if (!alive) return;
        const denied = failure?.status === 403 || /permission/i.test(failure?.message || "");
        setState({ admins: null, roster: null, denied, error: failure?.message || "", loading: false });
      });
    return () => {
      alive = false;
    };
  }, []);

  const byId = new Map((state.roster || []).map((member) => [member.id, member]));
  const owner = state.admins?.owner_user_id ? byId.get(state.admins.owner_user_id) : null;
  const admins = (state.admins?.admin_user_ids || []).map((id) => byId.get(id)).filter(Boolean);

  return (
    <SettingsShell title={t("workspace.ownership.title")} subtitle={t("workspace.ownership.desc")}>
      {state.loading && (
        <p className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("workspace.loading")}
        </p>
      )}

      {state.denied && (
        <div
          role="status"
          data-testid="workspace-ownership-denied"
          className="flex items-start gap-2 rounded-lg bg-muted px-3 py-2 text-[12px]"
        >
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <span>{t("workspace.ownership.noPermission")}</span>
        </div>
      )}

      {state.error && !state.denied && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {t("workspace.loadFailed")}
        </div>
      )}

      {!state.denied && !state.error && (
        <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
          <SettingCard title={t("workspace.ownership.owner")} desc={t("workspace.ownership.owner.desc")}>
            <SettingRow label={owner?.full_name || "—"} desc={owner?.email || ""} last>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2 py-0.5 text-[11.5px] font-medium">
                <ShieldCheck className="h-3.5 w-3.5" />
                {t("workspace.role.owner")}
              </span>
            </SettingRow>
          </SettingCard>

          <SettingCard title={t("workspace.ownership.admins")} desc={t("workspace.ownership.admins.desc")}>
            {admins.length === 0 ? (
              <p className="py-2 text-[12.5px] text-muted-foreground">{t("workspace.ownership.noAdmins")}</p>
            ) : (
              admins.map((member, index) => (
                <SettingRow
                  key={member.id}
                  label={member.full_name}
                  desc={member.email}
                  last={index === admins.length - 1}
                >
                  <span className="text-[11.5px] font-medium text-muted-foreground">
                    {t(`workspace.role.${member.role_code}`)}
                  </span>
                </SettingRow>
              ))
            )}
          </SettingCard>
        </div>
      )}

      <div className="mt-6">
        <SettingCard title={t("workspace.ownership.transfer")} desc={t("workspace.ownership.transfer.desc")}>
          <p className="py-2 text-[12.5px] leading-relaxed text-muted-foreground">
            {t("workspace.ownership.transfer.unavailable", {
              owner: owner?.full_name || data?.name || "",
            })}
          </p>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
