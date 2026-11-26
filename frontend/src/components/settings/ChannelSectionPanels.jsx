/** Section 12's three cross-channel pages: data sync, external integrations, connection health.
 *
 * The channels themselves already have a screen — `/settings/channels` lists them and
 * `/settings/channels/:channel` opens one — and this file deliberately does not rebuild it. What
 * the Settings Center adds is the view ACROSS the channels: what is syncing and when it last
 * arrived, which integrations are not messaging channels at all, and one place where the health
 * of every connection is visible at once.
 *
 * Every row here is an `integrations` row read through `GET /integrations`. A channel's identity
 * IS its integration row (not its warehouse), so nothing on these pages invents a second model.
 * Credentials never leave the server: the list returns `credentials_verified`, never the secret.
 */
import React from "react";
import { Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { useI18n, useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import ChannelDiagnostics from "@/pages/settings/ChannelDiagnostics";

/** A channel is an integration row of kind "channel"; everything else is an external connection.
 * Kept as a plain function so the split can be tested without a network round trip.
 */
export function splitIntegrations(rows) {
  const list = Array.isArray(rows) ? rows : (rows?.items ?? []);
  return {
    channels: list.filter((r) => r.kind === "channel"),
    external: list.filter((r) => r.kind !== "channel"),
  };
}

function useIntegrations() {
  const [state, setState] = React.useState({ loading: true, rows: [], error: "" });

  React.useEffect(() => {
    let alive = true;
    api("/integrations")
      .then((res) => {
        const rows = Array.isArray(res) ? res : (res?.items ?? []);
        if (alive) setState({ loading: false, rows, error: "" });
      })
      .catch((e) => alive && setState({ loading: false, rows: [], error: e?.message || "" }));
    return () => {
      alive = false;
    };
  }, []);

  return state;
}

function Frame({ titleKey, descKey, footerKey, loading, error, children }) {
  const t = useT();
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.channels.loading")}
      </div>
    );
  }
  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      {error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.channels.loadError")}
        </p>
      ) : (
        children
      )}
      <p className="mt-3 text-[12px] text-muted-foreground">{t(footerKey)}</p>
    </SettingCard>
  );
}

/** Which channels are syncing, and when their last event actually arrived. */
export function DataSyncPanel() {
  const t = useT();
  const { loading, rows, error } = useIntegrations();
  const { channels } = splitIntegrations(rows);

  return (
    <Frame
      titleKey="settings.channels.dataSync.title"
      descKey="settings.channels.dataSync.desc"
      footerKey="settings.channels.dataSync.whereToEdit"
      loading={loading}
      error={error}
    >
      {channels.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.channels.dataSync.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {channels.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <span className="min-w-28 font-medium">{c.display_name || c.provider}</span>
              <Badge tone="muted">{c.provider}</Badge>
              <Badge tone="muted">
                {t("settings.channels.webhook")} {c.webhook_status}
              </Badge>
              <span className="num text-muted-foreground">
                {t("settings.channels.lastEvent")} {c.last_webhook_at || "—"}
              </span>
              <Link
                to={`/settings/channels/${c.provider}`}
                className="text-[12px] font-medium text-primary hover:underline"
              >
                {t("settings.channels.openChannel")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Frame>
  );
}

/** The integrations that are not messaging channels: the shop's other outbound connections. */
export function ExternalIntegrationsPanel() {
  const t = useT();
  const { loading, rows, error } = useIntegrations();
  const { external } = splitIntegrations(rows);

  return (
    <Frame
      titleKey="settings.channels.external.title"
      descKey="settings.channels.external.desc"
      footerKey="settings.channels.external.whereToEdit"
      loading={loading}
      error={error}
    >
      {external.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.channels.external.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {external.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
              <span className="min-w-28 font-medium">{r.display_name || r.provider}</span>
              <Badge tone="muted">{r.kind}</Badge>
              <Badge tone="muted">{r.status}</Badge>
              <Badge tone="muted">
                {r.credentials_verified
                  ? t("settings.channels.verified")
                  : t("settings.channels.notVerified")}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Frame>
  );
}

/** Every connection's health in one place, reusing the diagnostics the channels screen already has. */
export function ConnectionHealthPanel() {
  const t = useT();
  const { lang } = useI18n();
  const { loading, rows, error } = useIntegrations();
  const { channels } = splitIntegrations(rows);

  return (
    <div className="space-y-3">
      <Frame
        titleKey="settings.channels.health.title"
        descKey="settings.channels.health.desc"
        footerKey="settings.channels.health.whereToEdit"
        loading={loading}
        error={error}
      >
        {channels.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t("settings.channels.health.empty")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {channels.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-2 py-2 text-[13px]">
                <span className="min-w-28 font-medium">{c.display_name || c.provider}</span>
                <Badge tone="muted">{c.status}</Badge>
                <Badge tone="muted">
                  {c.credentials_verified
                    ? t("settings.channels.verified")
                    : t("settings.channels.notVerified")}
                </Badge>
                {c.missing_scopes?.length ? (
                  <Badge tone="muted">
                    {t("settings.channels.missingScopes")} {c.missing_scopes.length}
                  </Badge>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Frame>

      {channels.map((c) => (
        <ChannelDiagnostics key={`diag-${c.id}`} channel={c} isAr={lang === "ar"} />
      ))}
    </div>
  );
}
