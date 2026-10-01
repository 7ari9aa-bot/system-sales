import React from "react";
import { UserPlus, Copy, X } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { getTokens, api } from "@/lib/api";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/dashboard/ui";

function tenantIdFromAccessToken() {
  try {
    const payload = getTokens()?.access_token?.split(".")[1];
    if (!payload) return null;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(window.atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="))).tenant_id || null;
  } catch {
    return null;
  }
}

const ROLE_TONE = { owner: "primary", manager: "warning", staff: "muted" };

export default function MembersSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const isAr = lang === "ar";
  const tenantId = tenantIdFromAccessToken() || (user?.tenants?.length === 1 ? user.tenants[0].id : null);
  const tenant = user?.tenants?.find((item) => item.id === tenantId) || null;
  const [invitations, setInvitations] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [revoking, setRevoking] = React.useState("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [roleCode, setRoleCode] = React.useState("staff");
  const [error, setError] = React.useState("");
  const [createdInvite, setCreatedInvite] = React.useState(null);

  const loadInvitations = React.useCallback(async () => {
    try {
      const rows = await api("/invitations");
      setInvitations(Array.isArray(rows) ? rows : []);
      setError("");
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر تحميل الدعوات" : "Could not load invitations"));
    } finally {
      setLoading(false);
    }
  }, [isAr]);

  React.useEffect(() => { void loadInvitations(); }, [loadInvitations]);

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
      await loadInvitations();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إرسال الدعوة" : "Could not create the invitation"));
    } finally {
      setSaving(false);
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
      await loadInvitations();
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

  const currentRole = tenant?.role_code || "—";
  const pendingInvitations = (invitations || []).filter((item) => item.status === "pending");

  return (
    <SettingsShell
      title={t("settings.members")}
      subtitle={t("settings.members.desc")}
      actions={
        <Button type="button" onClick={() => { setCreatedInvite(null); setFormOpen((open) => !open); }} className="gap-1.5">
          <UserPlus className="h-4 w-4" /> {t("members.invite")}
        </Button>
      }
    >
      {error && <div role="alert" className="mb-4 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}

      {createdInvite && (
        <div className="mb-4 rounded-xl border border-success/30 bg-success/5 p-4">
          <div className="text-[13px] font-semibold">{isAr ? `تم إنشاء دعوة لـ ${createdInvite.email}` : `Invitation created for ${createdInvite.email}`}</div>
          <p className="mt-1 text-[12px] text-muted-foreground">{isAr ? "انسخ رابط الدعوة وأرسله للعضو. سيظهر التوكن الكامل مرة واحدة فقط." : "Copy and send this invite link. The full invitation token is shown only once."}</p>
          <div className="mt-3 flex flex-col sm:flex-row gap-2">
            <Input aria-label={isAr ? "رابط الدعوة" : "Invitation link"} readOnly value={createdInvite.inviteUrl} className="text-xs" />
            <Button type="button" variant="outline" onClick={copyInvite} className="shrink-0"><Copy className="mr-1.5 h-4 w-4" />{isAr ? "نسخ الرابط" : "Copy link"}</Button>
            <Button type="button" variant="ghost" aria-label={isAr ? "إخفاء الرابط" : "Dismiss invite link"} onClick={() => setCreatedInvite(null)}><X className="h-4 w-4" /></Button>
          </div>
        </div>
      )}

      {formOpen && (
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

      <SettingCard>
        <div className="mb-3 flex items-center gap-3 rounded-lg bg-surface/60 px-3 py-3">
          <span className="h-9 w-9 rounded-full bg-accent/15 text-accent grid place-items-center text-[11px] font-semibold">
            {(user?.full_name || user?.email || "?").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium truncate">{user?.full_name || "—"}</div>
            <div className="text-[11.5px] text-muted-foreground truncate">{user?.email || "—"}</div>
          </div>
          <Badge tone={ROLE_TONE[currentRole] || "muted"}>{currentRole === "—" ? currentRole : t(`members.role.${currentRole}`)}</Badge>
        </div>

        <div className="overflow-x-auto -mx-5 px-5">
          <table className="w-full text-left">
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
                <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{isAr ? "جارٍ تحميل الدعوات…" : "Loading invitations…"}</td></tr>
              ) : invitations == null && error ? (
                <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">
                  <span>{isAr ? "تعذر تحميل الدعوات." : "Invitations could not be loaded."}</span>
                  <Button type="button" variant="outline" onClick={() => void loadInvitations()} className="ml-3">{isAr ? "إعادة المحاولة" : "Retry"}</Button>
                </td></tr>
              ) : pendingInvitations.length === 0 ? (
                <tr><td colSpan="4" className="py-6 text-center text-[12.5px] text-muted-foreground">{isAr ? "لا توجد دعوات معلّقة." : "No pending invitations."}</td></tr>
              ) : pendingInvitations.map((invitation) => (
                <tr key={invitation.id} className="border-b border-border last:border-0">
                  <td className="py-3"><div className="text-[13px] font-medium truncate">{invitation.email}</div></td>
                  <td className="py-3 hidden sm:table-cell"><Badge tone={ROLE_TONE[invitation.role_code] || "muted"}>{invitation.role_code ? t(`members.role.${invitation.role_code}`) : "—"}</Badge></td>
                  <td className="py-3"><span className="text-[12.5px] text-muted-foreground">{invitation.status}</span></td>
                  <td className="py-3 text-right">
                    <button type="button" aria-label={isAr ? `إلغاء دعوة ${invitation.email}` : `Revoke invitation for ${invitation.email}`} disabled={revoking === invitation.id} onClick={() => revoke(invitation)} className="h-7 w-7 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground disabled:opacity-50">
                      <X className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
          {isAr ? "الواجهة الحالية تعرض حسابك والدعوات المعلّقة فقط؛ لا يوفر الـAPI الحالي قائمة بأعضاء مساحة العمل كاملة." : "This screen shows your account and pending invitations. The current API does not expose the full workspace member roster."}
        </p>
      </SettingCard>
    </SettingsShell>
  );
}
