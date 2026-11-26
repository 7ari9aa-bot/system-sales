/** Section 17's surfaces: what the shop holds, how long it keeps it, and what it was asked to do.
 *
 * Three shapes, all read-only over a module that already owns the record:
 * - KeyValuePanel  : one read model (GET /analytics/retention), rendered as label/value.
 * - GenericListPanel: a list whose row shape may grow (imports, consents, data requests), rendered
 *   generically so a new field never becomes an em dash on the page.
 * - StaticNotePanel: a page whose engine does not exist yet, saying so plainly instead of showing
 *   an empty editor that would write nothing.
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

const SKIP = new Set(["id", "created_by_id", "updated_date"]);

/** The fields of one row that are worth reading on a screen, humanised. */
export function rowPairs(row, limit = 4) {
  if (!row || typeof row !== "object") return [];
  return Object.entries(row)
    .filter(([k, v]) => !SKIP.has(k) && (v === null || ["string", "number", "boolean"].includes(typeof v)))
    .slice(0, limit)
    .map(([k, v]) => [
      String(k).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "✓" : "✗") : String(v),
    ]);
}

function Frame({ titleKey, descKey, footerKey, state, empty, children }) {
  const t = useT();
  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.data.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.data.loadError")}
        </p>
      ) : empty ? (
        <p className="text-[13px] text-muted-foreground">{t(empty)}</p>
      ) : (
        children
      )}
      {footerKey ? <p className="mt-3 text-[12px] text-muted-foreground">{t(footerKey)}</p> : null}
    </SettingCard>
  );
}

export function KeyValuePanel({ endpoint, titleKey, descKey, footerKey, emptyKey }) {
  const state = useJson(endpoint);
  const data = state.data;
  const pairs =
    data && typeof data === "object" && !Array.isArray(data)
      ? Object.entries(data)
          .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v))
          .map(([k, v]) => [
            String(k).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
            v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "✓" : "✗") : String(v),
          ])
      : [];
  return (
    <Frame
      titleKey={titleKey}
      descKey={descKey}
      footerKey={footerKey}
      state={state}
      empty={pairs.length === 0 ? emptyKey : null}
    >
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {pairs.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border p-3">
            <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-[14px] font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
    </Frame>
  );
}

export function GenericListPanel({ endpoint, titleKey, descKey, footerKey, emptyKey }) {
  const state = useJson(endpoint);
  const raw = state.data;
  const rows = Array.isArray(raw) ? raw : (raw?.items ?? []);
  return (
    <Frame
      titleKey={titleKey}
      descKey={descKey}
      footerKey={footerKey}
      state={state}
      empty={rows.length === 0 ? emptyKey : null}
    >
      <ul className="divide-y divide-border">
        {rows.map((row, i) => (
          <li key={row.id || i} className="flex flex-wrap gap-x-4 gap-y-1 py-2 text-[12px]">
            {rowPairs(row).map(([label, value]) => (
              <span key={label} className="text-muted-foreground">
                {label}: <span className="text-foreground">{value}</span>
              </span>
            ))}
          </li>
        ))}
      </ul>
    </Frame>
  );
}

/** A page whose engine does not exist yet. It says what is missing and why it is not a switch. */
export function StaticNotePanel({ titleKey, descKey, bodyKey }) {
  const t = useT();
  return (
    <SettingCard title={t(titleKey)} desc={t(descKey)}>
      <p className="text-[13px] text-muted-foreground">{t(bodyKey)}</p>
    </SettingCard>
  );
}

/** The DR position as pairs: the policy numbers first, then the drill evidence.
 *
 * Exported so the formatting is testable without a render: the page's whole claim
 * is "here is what we can recover", and a formatter that silently dropped the
 * health flag would turn an overdue drill into a reassuring table.
 */
export function drSummary(data) {
  if (!data || typeof data !== "object") return [];
  const pick = (k) => data[k] ?? "—";
  const pairs = [
    ["RPO (minutes)", pick("rpo_minutes")],
    ["RTO (minutes)", pick("rto_minutes")],
    ["Backup retention (days)", pick("backup_retention_days")],
    ["PITR window (days)", pick("pitr_window_days")],
    ["Drill schedule", pick("restore_test_cron")],
    ["Last drill", pick("last_restore_test_at")],
    ["Last drill result", pick("last_restore_test_status")],
  ];
  // The two claims that matter after an incident, stated as words rather than a flag.
  pairs.push(["Recoverable", data.healthy ? "yes" : "not proven"]);
  pairs.push(["Drill overdue", data.restore_test_overdue ? "yes" : "no"]);
  return pairs.map(([label, value]) => [
    label,
    value === null || value === "" ? "—" : typeof value === "boolean" ? (value ? "✓" : "✗") : String(value),
  ]);
}

export function DRPanel({ titleKey, descKey, footerKey, noteKey }) {
  const t = useT();
  const state = useJson("/platform/dr");
  const pairs = drSummary(state.data);
  const drills = state.data?.restore_tests ?? [];
  return (
    <Frame titleKey={titleKey} descKey={descKey} footerKey={footerKey} state={state} empty={null}>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {pairs.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border p-3">
            <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-[14px] font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <h4 className="mt-5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
        {t("settings.data.backups.drills")}
      </h4>
      {drills.length === 0 ? (
        <p className="mt-1 text-[13px] text-muted-foreground">{t("settings.data.backups.noDrills")}</p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {drills.map((run) => (
            <li key={run.id} className="flex flex-wrap gap-x-4 gap-y-1 py-2 text-[12px]">
              {rowPairs(run).map(([label, value]) => (
                <span key={label} className="text-muted-foreground">
                  {label}: <span className="text-foreground">{value}</span>
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {noteKey ? (
        <p className="mt-4 rounded-lg border border-amber-300/60 bg-amber-50 p-3 text-[12px] text-amber-900">
          {t(noteKey)}
        </p>
      ) : null}
    </Frame>
  );
}
