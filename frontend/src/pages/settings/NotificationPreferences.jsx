import React from "react";
import { BellOff, Loader2, Mail, Smartphone, Sparkles } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";

/** The person's own notifications: which channels reach them, and when to be quiet.

 * These are personal, not workspace policy: nobody needs an admin's permission to
 * decide whether they want email. The workspace still holds the master switch for a
 * channel — a shop with no mail provider configured must not send mail — so the page
 * says so beside a channel instead of offering a switch that changes nothing.

 * In-app is shown but not switchable. The bell row is the record of what happened;
 * turning it off would not stop the event, only the person's knowledge of it.
 */
const CHANNEL_ICON = { in_app: BellOff, email: Mail, push: Smartphone };

/** The channels this product has, drawn before the request answers.
 *
 * The server's answer is the truth about the VALUES; this list is the truth about
 * which channels exist. Rendering from it means the screen does not flash an empty
 * card while the request is in flight, and the switches appear in a stable order.
 * Channels the deployment does not send (no SMS or WhatsApp provider is wired) are
 * simply not here: a switch that changes nothing is worse than no switch.
 */
const CHANNELS = [
  { channel: "in_app", label_key: "notif.channel.inApp", locked: true, enabled: true },
  { channel: "email", label_key: "notif.channel.email", locked: false, enabled: true },
  { channel: "push", label_key: "notif.channel.push", locked: false, enabled: false },
];

function Switch({ checked, onChange, label, testid, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked === true}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      data-testid={testid}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
        checked === true ? "bg-primary" : "bg-muted"
      }`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
          checked === true ? "left-[22px]" : "left-0.5"
        }`}
      />
    </button>
  );
}

export default function NotificationPreferences() {
  const t = useT();
  const [state, setState] = React.useState(null);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api("/users/me/notification-preferences")
      .then((data) => {
        if (alive) setState(data);
      })
      .catch(() => {
        if (alive) setError(t("notif.loadFailed"));
      });
    return () => {
      alive = false;
    };
  }, [t]);

  async function save(field, body) {
    if (busy) return;
    setBusy(field);
    setError("");
    setNotice("");
    try {
      const next = await api("/users/me/notification-preferences", {
        method: "PUT",
        body,
      });
      setState(next);
      setNotice(t("notif.saved"));
    } catch (failure) {
      setError(failure?.message || t("notif.saveFailed"));
    } finally {
      setBusy("");
    }
  }

  const serverChannels = state?.channels || [];
  const channels = CHANNELS.map((local) => {
    const remote = serverChannels.find((item) => item.channel === local.channel);
    return {
      ...local,
      label_key: remote?.label_key || local.label_key,
      enabled: remote ? remote.enabled : local.enabled,
      locked: remote ? remote.locked : local.locked,
    };
  });
  const quiet = state?.quiet_hours || { start: null, end: null, active_now: false };
  const workspace = state?.workspace || {};
  const quietOn = Boolean(quiet.start && quiet.end);

  return (
    <SettingsShell title={t("settings.notifications")} subtitle={t("settings.notifications.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("notif.channels.title")} desc={t("notif.channels.desc")}>
          {channels.map((channel, index) => {
            const Icon = CHANNEL_ICON[channel.channel] || BellOff;
            const silent = channel.channel !== "in_app" && workspace[channel.channel] === false;
            return (
              <SettingRow
                key={channel.channel}
                label={t(channel.label_key)}
                desc={
                  channel.locked
                    ? t("notif.channel.inApp.desc")
                    : silent
                      ? t("notif.channel.workspaceOff")
                      : t(`notif.channel.${channel.channel}.desc`)
                }
                last={index === channels.length - 1}
              >
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                  <Switch
                    label={t(channel.label_key)}
                    testid={`notif-${channel.channel}`}
                    checked={channel.enabled}
                    disabled={channel.locked || Boolean(busy) || state == null}
                    onChange={(value) => save(channel.channel, { [`${channel.channel}_enabled`]: value })}
                  />
                </div>
              </SettingRow>
            );
          })}
        </SettingCard>

        <SettingCard title={t("notif.quiet.title")} desc={t("notif.quiet.desc")}>
          <SettingRow label={t("notif.quiet.enable")} desc={t("notif.quiet.enable.desc")}>
            <Switch
              label={t("notif.quiet.enable")}
              testid="notif-quiet-toggle"
              checked={quietOn}
              disabled={Boolean(busy) || state == null}
              onChange={(value) =>
                save(
                  "quiet",
                  value
                    ? { quiet_start: "22:00", quiet_end: "07:00" }
                    : { quiet_start: "", quiet_end: "" }
                )
              }
            />
          </SettingRow>
          <SettingRow label={t("notif.quiet.start")} desc={t("notif.quiet.start.desc")}>
            <input
              type="time"
              value={quiet.start || "22:00"}
              disabled={!quietOn || Boolean(busy)}
              onChange={(event) =>
                save("quiet-start", { quiet_start: event.target.value, quiet_end: quiet.end })
              }
              data-testid="notif-quiet-start"
              aria-label={t("notif.quiet.start")}
              dir="ltr"
              className="h-9 rounded-md border border-border bg-card px-2 text-[12.5px]"
            />
          </SettingRow>
          <SettingRow
            label={t("notif.quiet.end")}
            desc={t("notif.quiet.timezone", { zone: state?.timezone || "UTC" })}
            last
          >
            <input
              type="time"
              value={quiet.end || "07:00"}
              disabled={!quietOn || Boolean(busy)}
              onChange={(event) =>
                save("quiet-end", { quiet_start: quiet.start, quiet_end: event.target.value })
              }
              data-testid="notif-quiet-end"
              aria-label={t("notif.quiet.end")}
              dir="ltr"
              className="h-9 rounded-md border border-border bg-card px-2 text-[12.5px]"
            />
          </SettingRow>
        </SettingCard>
      </div>

      <div className="mt-6 space-y-2">
        {busy && (
          <p className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("notif.saving")}
          </p>
        )}
        {quiet.active_now && (
          <div
            role="status"
            className="inline-flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-[12px]"
            data-testid="notif-quiet-active"
          >
            <BellOff className="h-3.5 w-3.5" />
            {t("notif.quiet.activeNow")}
          </div>
        )}
        {error && (
          <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
            {error}
          </div>
        )}
        {notice && !error && (
          <div
            role="status"
            className="inline-flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-[12px]"
            data-testid="notif-notice"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {notice}
          </div>
        )}
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("notif.footnote")}</p>
      </div>
    </SettingsShell>
  );
}
