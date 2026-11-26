import React from "react";
import { UserPlus, Copy, X } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import TeamPolicyCard from "@/components/settings/TeamPolicyCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/dashboard/ui";

const ROLE_TONE = { owner: "primary", manager: "warning", staff: "muted" };

const initials = (member) =>
  (member?.full_name || member?.email || "?")
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

export default function MembersSettings({ view = "all" }) {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const isAr = lang === "ar";
  const tenantId = activeTenantId(user);
  // Two entry points, one implementation: the Team section shows the roster on its
  // "members" page and the invite form on its "invitations" page, and /settings/members
  // keeps showing both exactly as it did before the split.
  const showMembers = view === "all" || view === "members";
  const showInvitations = view === "all" || view === "invitations";
  // Who is in the workspace comes from GET /users (the same roster the cashier's grant picker
  // reads); what is still on its way comes from /invitations. The page shows both because
  // "who has access" is one question, and it used to answer half of it while claiming the API
  // could not answer the other half at all.
  const [members, setMembers] = React.useState(null);
  const [invitations, setInvitations] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [revoking, setRevoking] = React.useState("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [roleCode, setRoleCode] = React.useState("staff");
  const [error, setError] = React.useState("");
  const [createdInvite, setCreatedInvite] = React.useState(null);
  const [busyMember, setBusyMember] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const [roster, invites] = await Promise.all([api("/users"), api("/invitations")]);
      setMembers(Array.isArray(roster) ? roster : []);
      setInvitations(Array.isArray(invites) ? invites : []);
      setError("");
    } catch (err) {
      setMembers(null);
      setInvitations(null);
      setError(err?.message || (isAr ? "تعذر تحميل الأعضاء" : "Could not load members"));
    } finally {
      setLoading(false);
    }
  }, [isAr]);

  React.useEffect(() => { void load(); }, [load]);

  async function invite(event) {
    event.preventDefault();
    if (!tenantId) {
      setError(isAr ? "تعذر تحديد مساحة العمل الحالية." : "Could not determine the active workspace.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const invitation = await api(`/tenants/${tenantId}/invitations`, {
        method: "POST",
        body: { email: email.trim(), role_code: roleCode },
      });
      const inviteUrl = `${window.location.origin}/accept-invitation?token=${encodeURIComponent(invitation.token)}`;
      setCreatedInvite({ email: invitation.email, inviteUrl });
      setEmail("");
      setRoleCode("staff");
      setFormOpen(false);
      await load();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إرسال الدعوة" : "Could not create the invitation"));
    } finally {
      setSaving(false);
    }
  }

  async function changeRole(member, nextRole) {
    if (!tenantId || busyMember) return;
    setBusyMember(member.id);
    setError("");
    try {
      await api(`/tenants/${tenantId}/members/${member.id}`, {
        method: "PUT",
        body: { role_code: nextRole },
      });
      await load();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر تغيير الصلاحية" : "Could not change the role"));
    } finally {
      setBusyMember("");
    }
  }

  async function removeMember(member) {
    if (!tenantId || busyMember) return;
    const confirmed = window.confirm(
      isAr
        ? `إزالة ${member.full_name || member.email} من مساحة العمل؟ سيفقد الوصول فورًا.`
        : `Remove ${member.full_name || member.email} from the workspace? They lose access immediately.`,
    );
    if (!confirmed) return;
    setBusyMember(member.id);
    setError("");
    try {
      await api(`/tenants/${tenantId}/members/${member.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إزالة العضو" : "Could not remove the member"));
    } finally {
      setBusyMember("");
    }
  }

  async function revoke(invitation) {
    const confirmed = window.confirm(isAr
      ? `هل تريد إلغاء الدعوة المرسلة إلى ${invitation.email}؟`
      : `Revoke the invitation sent to ${invitation.email}?`);
    if (!confirmed) return;
    setRevoking(invitation.id);
    setError("");
    try {
      await api(`/invitations/${invitation.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إلغاء الدعوة" : "Could not revoke the invitation"));
    } finally {
      setRevoking("");
    }
  }

  async function copyInvite() {
    try {
      await navigator.clipboard.writeText(createdInvite.inviteUrl);
    } catch {
      setError(isAr ? "تعذر النسخ تلقائيًا؛ انسخ الرابط يدويًا." : "Could not copy automatically; copy the link manually.");
    }
  }

  const rows = members || [];
  const pendingInvitations = (invitations || []).filter((item) => item.status === "pending");

  return (
    <SettingsShell
      title={t("settings.members")}
      subtitle={t("settings.members.desc")}
      actions={
        showInvitations ? (
          <Button type="button" onClick={() => { setCreatedInvite(null); setFormOpen((open) => !open); }} className="gap-1.5" data-testid="members-invite">
            <UserPlus className="h-4 w-4" /> {t("members.invite")}
          </Button>
        ) : null
      }
    >
      {error && <div role="alert" className="mb-3 text-[12px] text-destructive">{error}</div>}

      {showInvitations && createdInvite && (
        <div className="mb-4 border-b border-border pb-4">
          <div className="text-[13px] font-semibold">{isAr ? `تم إنشاء دعوة لـ ${createdInvite.email}` : `Invitation created for ${createdInvite.email}`}</div>
          <p className="mt-1 text-[12px] text-muted-foreground">{isAr ? "انسخ رابط الدعوة وأرسله للعضو. سيظهر التوكن الكامل مرة واحدة فقط." : "Copy and send this invite link. The full invitation token is shown only once."}</p>
          <div className="mt-3 flex flex-col sm:flex-row gap-2">
            <Input aria-label={isAr ? "رابط الدعوة" : "Invitation link"} readOnly value={createdInvite.inviteUrl} className="text-xs" />
            <Button type="button" variant="outline" onClick={copyInvite} className="shrink-0"><Copy className="me-1.5 h-4 w-4" />{isAr ? "نسخ الرابط" : "Copy link"}</Button>
            <Button type="button" variant="ghost" aria-label={isAr ? "إخفاء الرابط" : "Dismiss invite link"} onClick={() => setCreatedInvite(null)}><X className="h-4 w-4" /></Button>
          </div>
        </div>
      )}

      {showInvitations && formOpen && (
        <SettingCard title={isAr ? "دعوة عضو" : "Invite a member"} className="mb-4">
          <form onSubmit={invite} className="grid gap-3 py-2 sm:grid-cols-[1fr_180px_auto] sm:items-end">
            <label className="grid gap-1.5 text-[12px] text-muted-foreground">
              {isAr ? "البريد الإلكتروني" : "Email address"}
              <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
            </label>
            <label className="grid gap-1.5 text-[12px] text-muted-foreground">
              {isAr ? "الصلاحية" : "Role"}
              <select value={roleCode} onChange={(event) => setRoleCode(event.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px] text-foreground">
                <option value="staff">{t("members.role.staff")}</option>
                <option value="manager">{t("members.role.manager")}</option>
              </select>
            </label>
            <Button type="submit" disabled={saving || !tenantId}>{saving ? "…" : t("members.invite")}</Button>
          </form>
          {!tenantId && <p className="text-[11.5px] text-destructive">{isAr ? "تأكد من اختيار مساحة عمل واحدة قبل إرسال الدعوات." : "Select one active workspace before sending invitations."}</p>}
        </SettingCard>
      )}

      {showInvitations && <TeamPolicyCard />}

      {showMembers && (
      <SettingCard title={t("members.whoHasAccess")} desc={t("members.whoHasAccess.desc")}>
        <div className="overflow-x-auto">
          <table className="w-full text-start" data-testid="members-table">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                <th className="py-2.5 font-medium">{t("members.name")}</th>
                <th className="py-2.5 font-medium hidden sm:table-cell">{t("members.role")}</th>
                <th className="py-2.5 font-medium">{t("members.status")}</th>
                <th className="py-2.5 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{isAr ? "جارٍ تحميل الأعضاء…" : "Loading members…"}</td></tr>
              ) : members == null ? (
                <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">
                  <span>{isAr ? "تعذر تحميل الأعضاء." : "Members could not be loaded."}</span>
                  <Button type="button" variant="outline" onClick={() => void load()} className="ml-3">{t("common.retry", "Retry")}</Button>
                </td></tr>
              ) : (
                <>
                  {rows.map((member) => {
                    const isMe = member.id === user?.id;
                    return (
                      <tr key={member.id} className="border-b border-border" data-testid="member-row">
                        <td className="py-3">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span className="h-7 w-7 shrink-0 rounded-full bg-accent/15 text-accent grid place-items-center text-[10.5px] font-semibold">{initials(member)}</span>
                            <div className="min-w-0">
                              <div className="text-[13px] font-medium truncate">
                                {member.full_name || member.email}
                                {isMe && <span className="ms-2 text-[11px] font-normal text-muted-foreground">{t("members.you")}</span>}
                              </div>
                              <div className="text-[11.5px] text-muted-foreground truncate">{member.email}</div>
                            </div>
                          </div>
                        </td>
                        <td className="py-3 hidden sm:table-cell">
                          {member.role_code === "owner" || isMe ? (
                            <Badge tone={ROLE_TONE[member.role_code] || "muted"}>{member.role_code ? t(`members.role.${member.role_code}`) : "—"}</Badge>
                          ) : (
                            <select
                              aria-label={isAr ? `صلاحية ${member.full_name || member.email}` : `Role for ${member.full_name || member.email}`}
                              value={member.role_code || "staff"}
                              disabled={busyMember === member.id}
                              onChange={(event) => changeRole(member, event.target.value)}
                              className="h-8 rounded-md border border-input bg-background px-2 text-[12.5px] text-foreground disabled:opacity-50"
                              data-testid="member-role"
                            >
                              <option value="admin">{t("members.role.admin")}</option>
                              <option value="manager">{t("members.role.manager")}</option>
                              <option value="staff">{t("members.role.staff")}</option>
                              <option value="cashier">{t("members.role.cashier")}</option>
                            </select>
                          )}
                        </td>
                        <td className="py-3"><span className="text-[12.5px] text-muted-foreground">{t("members.active")}</span></td>
                        <td className="py-3 text-end">
                          {member.role_code !== "owner" && !isMe && (
                            <button
                              type="button"
                              aria-label={isAr ? `إزالة ${member.full_name || member.email}` : `Remove ${member.full_name || member.email}`}
                              disabled={busyMember === member.id}
                              onClick={() => removeMember(member)}
                              className="h-7 w-7 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground disabled:opacity-50"
                              data-testid="member-remove"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {pendingInvitations.map((invitation) => (
                    <tr key={invitation.id} className="border-b border-border last:border-0" data-testid="invitation-row">
                      <td className="py-3">
                        <div className="text-[13px] font-medium truncate">{invitation.email}</div>
                        <div className="text-[11.5px] text-muted-foreground">{t("members.invitedNotJoined")}</div>
                      </td>
                      <td className="py-3 hidden sm:table-cell"><Badge tone={ROLE_TONE[invitation.role_code] || "muted"}>{invitation.role_code ? t(`members.role.${invitation.role_code}`) : "—"}</Badge></td>
                      <td className="py-3"><Badge tone="warning">{t("members.pending")}</Badge></td>
                      <td className="py-3 text-end">
                        <button type="button" aria-label={isAr ? `إلغاء دعوة ${invitation.email}` : `Revoke invitation for ${invitation.email}`} disabled={revoking === invitation.id} onClick={() => revoke(invitation)} className="h-7 w-7 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground disabled:opacity-50">
                          <X className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {rows.length === 0 && pendingInvitations.length === 0 && (
                    <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{isAr ? "لا يوجد أعضاء ولا دعوات معلّقة." : "No members and no pending invitations."}</td></tr>
                  )}
                </>
              )}
            </tbody>
          </table>
        </div>
      </SettingCard>
      )}

      {showInvitations && !showMembers && (
        <SettingCard title={t("team.invitations.pending")} desc={t("team.invitations.pending.desc")}>
          <div className="overflow-x-auto">
            <table className="w-full text-start" data-testid="invitations-table">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="py-2.5 font-medium">{t("members.name")}</th>
                  <th className="py-2.5 font-medium hidden sm:table-cell">{t("members.role")}</th>
                  <th className="py-2.5 font-medium">{t("members.status")}</th>
                  <th className="py-2.5 w-8"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{t("team.loading")}</td></tr>
                ) : (invitations || []).length === 0 ? (
                  <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{t("team.invitations.none")}</td></tr>
                ) : (
                  (invitations || []).map((invitation) => (
                    <tr key={invitation.id} className="border-b border-border last:border-0" data-testid="invitation-row">
                      <td className="py-3 text-[13px] font-medium truncate">{invitation.email}</td>
                      <td className="py-3 hidden sm:table-cell"><Badge tone={ROLE_TONE[invitation.role_code] || "muted"}>{invitation.role_code ? t(`members.role.${invitation.role_code}`) : "—"}</Badge></td>
                      <td className="py-3"><Badge tone={invitation.status === "pending" ? "warning" : "muted"}>{t(`team.invitation.status.${invitation.status}`)}</Badge></td>
                      <td className="py-3 text-end">
                        {invitation.status === "pending" && (
                          <button type="button" aria-label={isAr ? `إلغاء دعوة ${invitation.email}` : `Revoke invitation for ${invitation.email}`} disabled={revoking === invitation.id} onClick={() => revoke(invitation)} className="h-7 w-7 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground disabled:opacity-50">
                            <X className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </SettingCard>
      )}
    </SettingsShell>
  );
}
