import React from "react";
import { api } from "@/lib/api";

/** Channels that have a Meta health report (the backend refuses any other). */
const META_CHANNELS = new Set(["messenger", "facebook", "instagram", "whatsapp"]);

const TONE = {
  ok: "text-emerald-700",
  warning: "text-amber-700",
  error: "text-destructive",
  unknown: "text-muted-foreground",
};

const MARK = { ok: "✓", warning: "!", error: "✕", unknown: "?" };

const CHECK_LABELS = {
  connection: ["الاتصال", "Connection"],
  permissions: ["الصلاحيات", "Permissions"],
  server_webhook: ["إعداد الخادم", "Server webhook"],
  asset_subscription: ["اشتراك الصفحة / الحساب", "Page / account subscription"],
  dashboard_webhook: ["Webhook في لوحة Meta", "Meta dashboard webhook"],
  recent_failures: ["أحداث فشلت", "Failed events"],
  recent_activity: ["آخر نشاط", "Recent activity"],
};

/** Whether this channel can show a health report: a Meta channel with a saved connection. */
export function hasDiagnostics(channel) {
  return Boolean(channel?.integrationId) && META_CHANNELS.has(channel?.id);
}

/** The label of one check, falling back to the key so a new check is never shown blank. */
export function checkLabel(key, isAr) {
  const pair = CHECK_LABELS[key];
  return pair ? pair[isAr ? 0 : 1] : String(key || "");
}

/** Worst problems first, so what to fix leads the list; the order among equals is kept. */
export function sortChecks(checks) {
  const rank = { error: 0, warning: 1, unknown: 2, ok: 3 };
  return [...(Array.isArray(checks) ? checks : [])]
    .map((check, index) => ({ check, index }))
    .sort((a, b) => (rank[a.check?.status] ?? 2) - (rank[b.check?.status] ?? 2) || a.index - b.index)
    .map(({ check }) => check);
}

/** Meta's own error, as the short line support asks for ("code 200 · message"). */
export function metaErrorLine(meta) {
  if (!meta || typeof meta !== "object") return "";
  const parts = [];
  if (meta.code != null) parts.push(`code ${meta.code}${meta.subcode != null ? `/${meta.subcode}` : ""}`);
  if (meta.message) parts.push(String(meta.message));
  return parts.join(" · ");
}

function DetailLines({ detail, isAr }) {
  if (!detail || typeof detail !== "object") return null;
  const lines = [];
  if (detail.callback_url) lines.push([isAr ? "رابط الـCallback" : "Callback URL", detail.callback_url]);
  if (Array.isArray(detail.fields) && detail.fields.length) lines.push([isAr ? "الحقول" : "Fields", detail.fields.join(", ")]);
  if (Array.isArray(detail.missing) && detail.missing.length) lines.push([isAr ? "ناقص" : "Missing", detail.missing.join(", ")]);
  if (Array.isArray(detail.missing_fields) && detail.missing_fields.length) lines.push([isAr ? "حقول ناقصة" : "Missing fields", detail.missing_fields.join(", ")]);
  const meta = metaErrorLine(detail.meta);
  if (meta) lines.push(["Meta", meta]);
  if (detail.last_error) lines.push([isAr ? "آخر خطأ" : "Last error", String(detail.last_error)]);
  if (detail.failed_events) lines.push([isAr ? "أحداث فاشلة" : "Failed events", String(detail.failed_events)]);
  if (!lines.length) return null;
  return (
    <dl className="mt-0.5 space-y-0.5 text-[11px] text-muted-foreground">
      {lines.map(([name, value]) => (
        <div key={name} className="flex gap-1.5">
          <dt className="shrink-0">{name}:</dt>
          <dd className="min-w-0 break-all" dir="ltr">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The report itself, separate from the loading so it can be rendered and tested on its own. */
export function DiagnosticsReport({ report, isAr }) {
  if (!report) return null;
  const checks = sortChecks(report.checks);
  return (
    <div data-testid="channel-diagnostics-report" className="mt-2 rounded-lg border border-border px-3 py-2">
      <ul className="space-y-2">
        {checks.map((check) => (
          <li key={check.key} data-status={check.status} className="text-[12px]">
            <div className={`flex items-start gap-1.5 ${TONE[check.status] || TONE.unknown}`}>
              <span aria-hidden="true" className="w-3 shrink-0 text-center font-semibold">{MARK[check.status] || MARK.unknown}</span>
              <div className="min-w-0">
                <span className="font-medium">{checkLabel(check.key, isAr)}</span>
                <span className="text-foreground"> — {check.summary}</span>
                {check.action && <div className="mt-0.5 text-foreground">{check.action}</div>}
                <DetailLines detail={check.detail} isAr={isAr} />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A button that asks for the report on demand: it makes live calls to Meta, so not on page load. */
export default function ChannelDiagnostics({ channel, isAr }) {
  const [state, setState] = React.useState({ phase: "idle", report: null, error: "" });
  if (!hasDiagnostics(channel)) return null;

  async function load() {
    setState({ phase: "loading", report: null, error: "" });
    try {
      const report = await api(`/integrations/${channel.integrationId}/diagnostics`);
      setState({ phase: "done", report, error: "" });
    } catch (e) {
      setState({
        phase: "error",
        report: null,
        error: e?.message || (isAr ? "تعذر فحص القناة." : "Could not check the channel."),
      });
    }
  }

  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={state.phase === "done" ? () => setState({ phase: "idle", report: null, error: "" }) : load}
        disabled={state.phase === "loading"}
        className="text-[11.5px] text-primary underline-offset-2 hover:underline disabled:opacity-60"
      >
        {state.phase === "loading"
          ? (isAr ? "جارٍ الفحص…" : "Checking…")
          : state.phase === "done"
            ? (isAr ? "إخفاء التشخيص" : "Hide diagnostics")
            : (isAr ? "تشخيص القناة" : "Diagnose channel")}
      </button>
      {state.phase === "error" && (
        <div role="alert" className="mt-1 text-[11.5px] text-destructive">{state.error}</div>
      )}
      {state.phase === "done" && <DiagnosticsReport report={state.report} isAr={isAr} />}
    </div>
  );
}
