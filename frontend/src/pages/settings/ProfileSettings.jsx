import React from "react";
import { Link } from "react-router-dom";
import { Camera, Loader2, Save, ShieldCheck, Store, Trash2 } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenant } from "@/lib/activeTenant";
import useAvatarUpload from "@/hooks/useAvatarUpload";
import SettingsShell, { SettingRow } from "@/components/settings/SettingsShell";
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

  const roleLabel = tenant?.role_code || "—";

  return (
    <SettingsShell title={t("settings.nav.profile")} subtitle={t("settings.profile.desc")}>
      {/* No boxes: one open page. The person on top, then plain rows separated by hairlines. */}
      <div className="max-w-3xl">
        <div className="flex flex-col gap-4 pb-5 sm:flex-row sm:items-center">
          <AccountAvatar user={user} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[17px] font-semibold leading-6">{user?.full_name || "—"}</div>
            <div className="truncate text-[13px] text-muted-foreground">{tenant?.name || "—"}</div>
          </div>
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
            className={`-mt-2 mb-3 text-[12px] ${avatar.error ? "text-destructive" : "text-muted-foreground"}`}
          >
            {avatar.error || avatar.notice}
          </p>
        )}

        <form onSubmit={saveName} className="border-t border-border">
          <SettingRow label={t("profile.fullName")} stretch>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                autoComplete="name"
                aria-label={t("profile.fullName")}
                className="min-w-0 flex-1 sm:w-64 sm:flex-none"
                data-testid="profile-name"
              />
              <Button
                type="submit"
                disabled={!nameChanged || savingName}
                className="gap-1.5"
                data-testid="profile-name-save"
              >
                {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {savingName ? "" : t("businessProfile.save")}
              </Button>
            </div>
          </SettingRow>
          {(nameError || nameNotice) && (
            <div
              role={nameError ? "alert" : "status"}
              data-testid="profile-name-message"
              className={`border-b border-border py-2 text-[12.5px] ${nameError ? "text-destructive" : "text-success"}`}
            >
              {nameError || nameNotice}
            </div>
          )}
        </form>
        <SettingRow label={t("profile.email")} desc={t("profile.email.locked")}>
          <span className="text-[13px] font-medium" dir="ltr">{user?.email || "—"}</span>
        </SettingRow>
        <SettingRow label={t("workspace.name")} desc={tenant?.name || "—"}>
          <Link
            to="/settings/workspace"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:underline"
          >
            <Store className="h-4 w-4" />
            {t("profile.link.workspace")}
          </Link>
        </SettingRow>
        <SettingRow label={t("workspace.role")}>
          <span className="text-[13px] font-medium">{roleLabel}</span>
        </SettingRow>
        <SettingRow label={t("settings.nav.security")} desc={t("profile.link.security.desc")} last>
          <Link
            to="/settings/security"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:underline"
          >
            <ShieldCheck className="h-4 w-4" />
            {t("profile.link.security")}
          </Link>
        </SettingRow>
      </div>
    </SettingsShell>
  );
}
