/** Section 20 — Developers & API, over the rows the platform already keeps.
 *
 * Four of the six pages have a real surface behind them, and two do not — which the map says
 * plainly instead of opening a screen of dead controls:
 *
 * - `WebhooksPanel` reads `GET /webhook-endpoints` and the new `GET /webhook-endpoints/deliveries`.
 *   A delivery row is the only honest answer to "did my endpoint receive it": status, attempts,
 *   response code and the stored error. The payload is deliberately not returned.
 * - `RateLimitsPanel` reads `GET /platform/rate-limits`, which reports the middleware's own
 *   bucket table and whether the limiter is enforcing. It is read-only because the ceiling is
 *   deployment configuration, not a shop setting.
 * - `DeveloperEnvironmentPanel` states the API origin and links the live OpenAPI document the
 *   server serves, so "where is the contract" has an answer that cannot go stale.
 * - `ConnectedAppsPanel` links to section 12's external integrations: the integrations table is
 *   where a connected app lives, and a second list here would be a second truth.
 */
import React from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { api, apiUrl } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

function useJson(path) {
  const [state, setState] = React.useState({ loading: true, data: null, error: "" });
  React.useEffect(() => {
    let alive = true;
    api(path)
      .then((data) => alive && setState({ loading: false, data, error: "" }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e?.message || "" }));
    return () => {
      alive = false;
    };
  }, [path]);
  return state;
}

function Frame({ title, desc, state, children, testId }) {
  const t = useT();
  return (
    <SettingCard title={title} desc={desc}>
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.data.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.data.loadError")}
        </p>
      ) : (
        <div data-testid={testId}>{children}</div>
      )}
    </SettingCard>
  );
}

const DELIVERY_TONE = {
  delivered: "success",
  queued: "warning",
  failed: "error",
  dead: "error",
};

export function WebhooksPanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const endpoints = useJson("/webhook-endpoints");
  const deliveries = useJson("/webhook-endpoints/deliveries");
  const endpointRows = Array.isArray(endpoints.data) ? endpoints.data : [];
  const deliveryRows = Array.isArray(deliveries.data?.items) ? deliveries.data.items : [];

  return (
    <>
      <Frame
        title={t("settings.developers.webhooks.title")}
        desc={t("settings.developers.webhooks.desc")}
        state={endpoints}
        testId="webhook-endpoints"
      >
        {endpointRows.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            {t("settings.developers.webhooks.empty")}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {endpointRows.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-2 py-2.5 text-[12.5px]">
                <code className="min-w-0 flex-1 truncate" dir="ltr">
                  {row.url}
                </code>
                <span className="text-[11.5px] text-muted-foreground">
                  {(row.events || []).join(", ") || (isAr ? "كل الأحداث" : "all events")}
                </span>
                <Badge tone={row.active ? "success" : "muted"}>
                  {row.active ? t("settings.developers.webhooks.active") : t("settings.developers.webhooks.inactive")}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Frame>

      <Frame
        title={t("settings.developers.deliveries.title")}
        desc={t("settings.developers.deliveries.desc")}
        state={deliveries}
        testId="webhook-deliveries"
      >
        {deliveryRows.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            {t("settings.developers.deliveries.empty")}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {deliveryRows.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[12px]">
                <span className="font-medium">{row.event_name}</span>
                <Badge tone={DELIVERY_TONE[row.status] || "muted"}>
                  {t(`settings.developers.deliveries.statuses.${row.status}`, row.status)}
                </Badge>
                <span className="text-muted-foreground">
                  {t("settings.developers.deliveries.attempts")}: {row.attempts}
                </span>
                {row.response_code != null && (
                  <span className="text-muted-foreground" dir="ltr">
                    HTTP {row.response_code}
                  </span>
                )}
                {row.last_error && (
                  <span className="min-w-0 flex-1 truncate text-destructive" dir="ltr">
                    {row.last_error}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("settings.developers.deliveries.whereToEdit")}
        </p>
      </Frame>
    </>
  );
}

export function RateLimitsPanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const state = useJson("/platform/rate-limits");
  const body = state.data || {};
  const buckets = Array.isArray(body.buckets) ? body.buckets : [];

  return (
    <Frame
      title={t("settings.developers.rateLimits.title")}
      desc={t("settings.developers.rateLimits.desc")}
      state={state}
      testId="rate-limits"
    >
      <div className="mb-2 flex items-center gap-2 text-[12.5px]">
        <span className="text-muted-foreground">{t("settings.developers.rateLimits.enforced")}:</span>
        <Badge tone={body.enforced ? "success" : "muted"}>
          {body.enforced
            ? t("settings.developers.rateLimits.on")
            : t("settings.developers.rateLimits.off")}
        </Badge>
        <span className="text-muted-foreground">
          {t("settings.developers.rateLimits.window")}: {body.window_seconds} {isAr ? "ثانية" : "s"}
        </span>
      </div>
      <ul className="divide-y divide-border">
        {buckets.map((row) => (
          <li key={row.bucket} className="flex items-center justify-between gap-3 py-2 text-[12.5px]">
            <code dir="ltr">{row.bucket}</code>
            <span className="tabular-nums text-muted-foreground">
              {row.limit} / {body.window_seconds}s
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.developers.rateLimits.whereToEdit")}
      </p>
    </Frame>
  );
}

export function ConnectedAppsPanel() {
  const t = useT();
  return (
    <SettingCard
      title={t("settings.developers.connectedApps.title")}
      desc={t("settings.developers.connectedApps.desc")}
    >
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        {t("settings.developers.connectedApps.body")}{" "}
        <Link className="underline" to="/settings/channels/external-integrations">
          {t("settings.developers.connectedApps.link")}
        </Link>
      </p>
    </SettingCard>
  );
}

export function DeveloperEnvironmentPanel() {
  const t = useT();
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => {
    try {
      setOrigin(new URL(apiUrl("")).origin);
    } catch {
      setOrigin("");
    }
  }, []);
  const schemaHref = origin ? `${origin}/api/v1/openapi.json` : "/api/v1/openapi.json";

  return (
    <SettingCard
      title={t("settings.developers.environment.title")}
      desc={t("settings.developers.environment.desc")}
    >
      <dl className="space-y-2 text-[12.5px]">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">{t("settings.developers.environment.origin")}</dt>
          <dd className="min-w-0 truncate" dir="ltr">
            {origin || "—"}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">{t("settings.developers.environment.schema")}</dt>
          <dd className="min-w-0 truncate">
            <a className="underline" href={schemaHref} target="_blank" rel="noreferrer" dir="ltr">
              /api/v1/openapi.json
            </a>
          </dd>
        </div>
      </dl>
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.developers.environment.body")}
      </p>
    </SettingCard>
  );
}
