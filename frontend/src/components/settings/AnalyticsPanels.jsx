/** Section 14's read-only surfaces: what the shop is measuring, and the numbers it reports.
 *
 * Three rules drive this file.
 *
 * 1. A figure on this page comes from the analytics module, never from a guess. `/analytics/overview`,
 *    `/analytics/metrics/definitions` and `/analytics/revenue/summary` are the module's own read
 *    models, so the page renders what the server returned instead of inventing a metric.
 * 2. Nothing here is an editor. Reports and dashboards are produced by the analytics engine; a
 *    control on this page that changed nothing would be the defect the center exists to prevent.
 * 3. The shape is rendered generically (label + value) because the module's read models are allowed
 *    to add a field without a settings release. A hard-coded column list would silently show "—"
 *    the day a metric is renamed.
 */
import React from "react";
import { Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";

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

function humanise(key) {
  return String(key)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "✓" : "✗";
  if (typeof value === "number") return new Intl.NumberFormat().format(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Every scalar the read model returned, as label/value pairs. Arrays and objects are counted. */
export function scalarPairs(data) {
  if (!data || typeof data !== "object") return [];
  return Object.entries(data)
    .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v))
    .map(([k, v]) => [humanise(k), formatValue(v)]);
}

function KpiGrid({ pairs }) {
  if (pairs.length === 0) return null;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {pairs.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-border p-3">
          <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
          <dd className="num mt-1 text-[15px] font-semibold">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Frame({ titleKey, descKey, footerKey, state, children }) {
  const t = useT();
  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.analytics.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.analytics.loadError")}
        </p>
      ) : (
        children
      )}
      <p className="mt-3 text-[12px] text-muted-foreground">{t(footerKey)}</p>
    </SettingCard>
  );
}

/** Dashboards: the live overview the shop's own dashboard renders. */
export function OverviewPanel() {
  const t = useT();
  const state = useJson("/analytics/overview");
  const pairs = scalarPairs(state.data);
  return (
    <Frame
      titleKey="settings.analytics.overview.title"
      descKey="settings.analytics.overview.desc"
      footerKey="settings.analytics.overview.whereToEdit"
      state={state}
    >
      {pairs.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.analytics.overview.empty")}</p>
      ) : (
        <KpiGrid pairs={pairs} />
      )}
    </Frame>
  );
}

/** Metrics and indicators: the metric definitions the engine actually computes. */
export function MetricsPanel() {
  const t = useT();
  const state = useJson("/analytics/metrics/definitions");
  const raw = state.data;
  const rows = Array.isArray(raw) ? raw : (raw?.items ?? []);

  return (
    <Frame
      titleKey="settings.analytics.metrics.title"
      descKey="settings.analytics.metrics.desc"
      footerKey="settings.analytics.metrics.whereToEdit"
      state={state}
    >
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.analytics.metrics.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((row, i) => {
            const label = row.name || row.key || row.metric || `#${i + 1}`;
            const desc = row.description || row.label || row.formula || "";
            return (
              <li key={label} className="py-2 text-[13px]">
                <span className="font-medium">{label}</span>
                {desc ? <span className="ms-2 text-muted-foreground">{desc}</span> : null}
              </li>
            );
          })}
        </ul>
      )}
    </Frame>
  );
}

/** Reports: the revenue summary the module reports from the real order and invoice rows. */
export function ReportsPanel() {
  const t = useT();
  const state = useJson("/analytics/revenue/summary");
  const pairs = scalarPairs(state.data);
  return (
    <Frame
      titleKey="settings.analytics.reports.title"
      descKey="settings.analytics.reports.desc"
      footerKey="settings.analytics.reports.whereToEdit"
      state={state}
    >
      {pairs.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t("settings.analytics.reports.empty")}</p>
      ) : (
        <KpiGrid pairs={pairs} />
      )}
    </Frame>
  );
}
