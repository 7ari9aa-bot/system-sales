import React from "react";
import { Link } from "react-router-dom";
import { Camera, Loader2, Save, ShieldCheck, Store, Trash2 } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenant } from "@/lib/activeTenant";
import useAvatarUpload from "@/hooks/useAvatarUpload";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import AccountAvatar from "@/components/dashboard/AccountAvatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** The person: their picture, their name, their address, and the way out to their account.
 *
 * This page answers "who am I" and nothing else. The shop's name, its country, its currency and
 * the assistant's dialect used to sit here as well, which made a personal page the place where
 * business settings were edited. They now live where they belong (Workspace settings, AI) and are
 * linked from the Account card below.
 */
export default function ProfileSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user, refreshUser } = useAuth();
  const tenant = activeTenant(user);
  const avatar = useAvatarUpload();

  const [name, setName] = React.useState(user?.full_name || "");
  const [savingName, setSavingName] = React.useState(false);
  const [nameError, setNameError] = React.useState("");
  const [nameNotice, setNameNotice] = React.useState("");

  // A refreshed account (another tab, an avatar change) is the truth; only overwrite the field
  // when the owner is not mid-edit, so their typing is never yanked away.
  const storedName = user?.full_name || "";
  React.useEffect(() => {
    setName((current) => (current === "" ? storedName : current));
  }, [storedName]);

  const nameChanged = name.trim() !== "" && name.trim() !== storedName.trim();

  async function saveName(event) {
    event.preventDefault();
    if (!nameChanged || savingName) return;
    setSavingName(true);
    setNameError("");
    setNameNotice("");
    try {
      const updated = await api("/users/me", { method: "PATCH", body: { full_name: name } });
      // render what the server stored (it collapses whitespace), then refresh the shell so the
      // sidebar, account menu and header show the same name
      setName(updated?.full_name || name.trim());
      await refreshUser();
      setNameNotice(t("profile.name.saved"));
    } catch (failure) {
      setNameError(failure?.message || t("profile.name.failed"));
    } finally {
      setSavingName(false);
    }
  }

  return (
    <SettingsShell title={t("settings.nav.profile")} subtitle={t("settings.profile.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("profile.identity")} desc={t("profile.identity.desc")}>
          <div className="flex flex-col gap-4 pt-3 sm:flex-row sm:items-center">
            <AccountAvatar user={user} size="lg" />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="gap-1.5"
                disabled={avatar.busy}
                onClick={avatar.pick}
              >
                {avatar.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
                {t(user?.avatar_url ? "account.avatar.change" : "account.avatar.add")}
              </Button>
              {user?.avatar_url && (
                <Button
                  type="button"
                  variant="ghost"
                  className="gap-1.5 text-destructive hover:text-destructive"
                  disabled={avatar.busy}
                  onClick={() => void avatar.remove()}
                >
                  <Trash2 className="h-4 w-4" />
                  {t("account.avatar.remove")}
                </Button>
              )}
              <input
                ref={avatar.inputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                aria-label={t("account.avatar.pick")}
                onChange={avatar.upload}
              />
            </div>
          </div>
          {(avatar.error || avatar.notice) && (
            <p
              role={avatar.error ? "alert" : "status"}
              className={`mt-2 text-[12px] ${avatar.error ? "text-destructive" : "text-muted-foreground"}`}
            >
              {avatar.error || avatar.notice}
            </p>
          )}

          <form className="mt-4 grid gap-3 border-t border-border pt-4 sm:grid-cols-2" onSubmit={saveName}>
            <label className="block">
              <span className="text-[11.5px] text-muted-foreground">{t("profile.fullName")}</span>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                autoComplete="name"
                className="mt-1"
                data-testid="profile-name"
              />
            </label>
            <div className="block">
              <span className="text-[11.5px] text-muted-foreground">{t("profile.email")}</span>
              <div className="mt-1 rounded-md border border-border bg-surface px-3 py-2 text-[13px] font-medium break-all" dir="ltr">
                {user?.email || "—"}
              </div>
            </div>
            <div className="sm:col-span-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-[11.5px] leading-relaxed text-muted-foreground max-w-md">
                {t("profile.email.locked")}
              </p>
              <Button
                type="submit"
                disabled={!nameChanged || savingName}
                className="gap-1.5 shrink-0"
                data-testid="profile-name-save"
              >
                <Save className="h-4 w-4" />
                {savingName ? "…" : t("businessProfile.save")}
              </Button>
            </div>
          </form>
          {(nameError || nameNotice) && (
            <div
              role={nameError ? "alert" : "status"}
              data-testid="profile-name-message"
              className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${nameError ? "bg-destructive/10 text-destructive" : "bg-success/10 text-foreground"}`}
            >
              {nameError || nameNotice}
            </div>
          )}
        </SettingCard>

        <SettingCard title={t("profile.account")}>
          <div className="pt-1">
            <SettingRow label={t("workspace.name")} desc={tenant?.name || "—"}>
              <Link
                to="/settings/workspace"
                className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:gap-2 transition-all"
              >
                <Store className="h-4 w-4" />
                {t("profile.link.workspace")}
              </Link>
            </SettingRow>
            <SettingRow label={t("workspace.role")}>
              <span className="text-[13px] font-medium">{tenant?.role_code || "—"}</span>
            </SettingRow>
            <SettingRow label={t("settings.nav.security")} desc={t("profile.link.security.desc")} last>
              <Link
                to="/settings/security"
                className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:gap-2 transition-all"
              >
                <ShieldCheck className="h-4 w-4" />
                {t("profile.link.security")}
              </Link>
            </SettingRow>
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-muted-foreground">
            {lang === "ar"
              ? "لهجة المساعد بقت في صفحة الذكاء الاصطناعي، واسم المحل والعملة والتوقيت في صفحة مساحة العمل."
              : "The assistant's dialect now lives on the AI page; the shop's name, currency and time zone live on Workspace settings."}
          </p>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
