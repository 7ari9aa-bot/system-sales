import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Eye,
  Lock,
  MousePointerClick,
  RefreshCw,
  Server,
  Unlock,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Badge, KpiCard, PageHeader, SectionCard } from "@/components/dashboard/ui";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "overview", ar: "نظرة عامة", en: "Overview" },
  { id: "tenants", ar: "المستأجرون", en: "Tenants" },
  { id: "visitors", ar: "الزوار", en: "Visitors" },
  { id: "system", ar: "الصحة", en: "System" },
];

const TONE = { healthy: "success", degraded: "warning", down: "destructive" };

function fmt(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString();
}

function time(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

export default function OwnerConsole() {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [overview, setOverview] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [visitors, setVisitors] = useState(null);
  const [system, setSystem] = useState(null);
  const [visitorSummary, setVisitorSummary] = useState(null);
  const [matrix, setMatrix] = useState(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [savingCell, setSavingCell] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    Promise.all([
      api("/owner/overview"),
      api("/owner/tenants?limit=50"),
      api("/owner/visitors?hours=24&limit=80"),
      api("/owner/system"),
      api("/owner/visitors/summary?hours=24"),
    ])
      .then(([ov, ten, vis, sys, summary]) => {
        if (!alive) return;
        setOverview(ov);
        setTenants(Array.isArray(ten?.items) ? ten.items : []);
        setVisitors(vis);
        setSystem(sys);
        setVisitorSummary(summary);
      })
      .catch((err) => {
        if (alive) setError(err?.message || L("تعذر تحميل كونسول المالك.", "Could not load the owner console."));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [refresh]);

  const accessMap = useMemo(() => {
    const map = new Map();
    for (const row of matrix?.access || []) {
      map.set(`${row.user_id}:${row.provider}`, row);
    }
    return map;
  }, [matrix]);

  async function openMatrix(tenantId) {
    setMatrixLoading(true);
    setTab("tenants");
    try {
      const data = await api(`/owner/tenants/${tenantId}/channels`);
      setMatrix(data);
    } catch (err) {
      setError(err?.message || L("تعذر تحميل مصفوفة القنوات.", "Could not load the channel matrix."));
    } finally {
      setMatrixLoading(false);
    }
  }

  async function toggleAccess(member, provider, enabled) {
    if (!matrix) return;
    const key = `${member.id}:${provider}`;
    setSavingCell(key);
    try {
      const saved = await api(
        `/owner/tenants/${matrix.tenant_id}/channels/${provider}/users/${member.id}`,
        { method: "PUT", body: { enabled, can_send: enabled } }
      );
      setMatrix((prev) => {
        if (!prev) return prev;
        const rest = (prev.access || []).filter(
          (row) => !(row.user_id === member.id && row.provider === provider)
        );
        return { ...prev, access: [...rest, saved] };
      });
    } catch (err) {
      setError(err?.message || L("تعذر تحديث صلاحية القناة.", "Could not update channel access."));
    } finally {
      setSavingCell("");
    }
  }

  const counts = overview?.counts || {};
  const subsystems = overview?.subsystems || [];
  const channelSummary = overview?.channels || [];

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title={L("كونسول المالك", "Owner console")}
        subtitle={L(
          "مركز تحكم كامل في المنصة، القنوات، المستخدمين، والزوار.",
          "Full control over the platform, channels, users, and visitors."
        )}
        actions={
          <button
            type="button"
            onClick={() => setRefresh((n) => n + 1)}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[12.5px] font-medium hover:bg-surface"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            {L("تحديث", "Refresh")}
          </button>
        }
      />

      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-[13px] text-destructive">
          {error}
        </div>
      )}

      <div className="mb-5 flex flex-wrap gap-1.5 rounded-xl border border-border bg-card p-1.5">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              "rounded-lg px-3.5 py-2 text-[13px] font-medium transition-colors",
              tab === item.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-surface"
            )}
          >
            {isAr ? item.ar : item.en}
          </button>
        ))}
      </div>

      {loading && !overview ? (
        <div className="grid min-h-48 place-items-center text-[13px] text-muted-foreground">
          {L("جارٍ تحميل حالة النظام…", "Loading system status…")}
        </div>
      ) : tab === "overview" ? (
        <OverviewTab
          L={L}
          counts={counts}
          subsystems={subsystems}
          channels={channelSummary}
          visitors={overview?.recent_visitors || []}
        />
      ) : tab === "tenants" ? (
        <TenantsTab
          L={L}
          tenants={tenants}
          matrix={matrix}
          matrixLoading={matrixLoading}
          accessMap={accessMap}
          savingCell={savingCell}
          onOpenMatrix={openMatrix}
          onToggle={toggleAccess}
        />
      ) : tab === "system" ? (
        <SystemTab L={L} data={system} summary={visitorSummary} />
      ) : (
        <VisitorsTab L={L} data={visitors} summary={visitorSummary} />
      )}
    </div>
  );
}

function OverviewTab({ L, counts, subsystems, channels, visitors }) {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label={L("المستأجرون", "Tenants")}
          value={fmt(counts.tenants)}
          sub={`${fmt(counts.active_tenants)} ${L("نشط", "active")}`}
          accent={{ icon: <Building2 />, bg: "bg-primary/10", color: "text-primary" }}
          to="/owner"
        />
        <KpiCard
          label={L("المستخدمون", "Users")}
          value={fmt(counts.users)}
          sub={`${fmt(counts.platform_admins)} ${L("أدمن منصة", "platform admins")}`}
          accent={{ icon: <Users />, bg: "bg-accent/10", color: "text-accent" }}
          to="/owner"
        />
        <KpiCard
          label={L("زوار 24 ساعة", "Visitors 24h")}
          value={fmt(counts.visitors_24h)}
          sub={`${fmt(counts.visitor_events_24h)} ${L("حدث", "events")}`}
          accent={{ icon: <Eye />, bg: "bg-success/10", color: "text-success" }}
          to="/owner"
        />
        <KpiCard
          label={L("Outbox معلّق", "Pending outbox")}
          value={fmt(counts.pending_outbox)}
          sub={`${fmt(counts.failed_webhooks_24h)} ${L("Webhook فاشل", "failed webhooks")}`}
          accent={{ icon: <AlertTriangle />, bg: "bg-warning/15", color: "text-warning" }}
          to="/owner"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionCard title={L("حالة النظام", "System health")}>
          <div className="space-y-2.5">
            {subsystems.map((row) => (
              <div key={row.name} className="flex items-start justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5">
                <div className="flex min-w-0 items-start gap-2">
                  <Server className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium capitalize">{row.name}</div>
                    {row.detail && <div className="text-[11.5px] text-muted-foreground">{row.detail}</div>}
                  </div>
                </div>
                <Badge tone={TONE[row.status] || "muted"}>{row.status}</Badge>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title={L("القنوات", "Channels")}>
          <div className="space-y-2">
            {channels.map((row) => (
              <div key={row.provider} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 px-3 py-2.5">
                <div>
                  <div className="text-[13px] font-medium">{row.display_name}</div>
                  <div className="text-[11.5px] text-muted-foreground">
                    {row.connected_tenants}/{row.total_tenants} {L("متصل", "connected")}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {row.attention > 0 && <Badge tone="warning">{row.attention} {L("تحتاج انتباه", "attention")}</Badge>}
                  <Badge tone={row.connected_tenants > 0 ? "success" : "muted"}>
                    {row.connected_tenants > 0 ? L("يعمل", "live") : L("غير متصل", "offline")}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      <SectionCard title={L("أحدث أحداث الزوار", "Latest visitor events")}>
        <div className="divide-y divide-border">
          {visitors.length === 0 ? (
            <div className="py-8 text-center text-[13px] text-muted-foreground">
              {L("لا توجد أحداث بعد.", "No events yet.")}
            </div>
          ) : visitors.map((event) => (
            <div key={event.id} className="flex items-center justify-between gap-3 py-2.5 text-[12.5px]">
              <div className="flex min-w-0 items-center gap-2">
                <MousePointerClick className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">{event.event_type}</span>
                <span className="truncate text-muted-foreground">{event.path}</span>
              </div>
              <span className="shrink-0 text-[11px] text-muted-foreground">{time(event.created_at)}</span>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function TenantsTab({ L, tenants, matrix, matrixLoading, accessMap, savingCell, onOpenMatrix, onToggle }) {
  return (
    <div className="space-y-4">
      <SectionCard title={L("المستأجرون", "Tenants")}>
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2.5 text-start font-medium">{L("الاسم", "Name")}</th>
                <th className="py-2.5 text-start font-medium">{L("الحالة", "Status")}</th>
                <th className="py-2.5 text-start font-medium">{L("المستخدمون", "Users")}</th>
                <th className="py-2.5 text-start font-medium">{L("القنوات", "Channels")}</th>
                <th className="py-2.5 text-start font-medium">{L("صرف الذكاء (الشهر)", "AI spend (month)")}</th>
                <th className="py-2.5 text-end font-medium">{L("تحكم", "Control")}</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id} className="border-b border-border/60 last:border-0">
                  <td className="py-3 font-medium">{tenant.name}</td>
                  <td className="py-3">
                    <Badge tone={tenant.is_active ? "success" : "warning"}>{tenant.lifecycle_state}</Badge>
                  </td>
                  <td className="py-3 tabular-nums">{fmt(tenant.users)}</td>
                  <td className="py-3 tabular-nums">{tenant.channels_connected}/{tenant.channels_total}</td>
                  <td className="py-3">
                    <SpendCell L={L} tenant={tenant} />
                  </td>
                  <td className="py-3 text-end">
                    <button
                      type="button"
                      onClick={() => onOpenMatrix(tenant.id)}
                      className="rounded-lg border border-border px-2.5 py-1.5 text-[12px] font-medium hover:bg-surface"
                    >
                      {L("فتح القنوات", "Open channels")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {matrixLoading && (
        <div className="grid min-h-32 place-items-center text-[13px] text-muted-foreground">
          {L("جارٍ تحميل مصفوفة القنوات…", "Loading channel matrix…")}
        </div>
      )}

      {matrix && !matrixLoading && (
        <SectionCard
          title={`${L("صلاحيات القنوات", "Channel access")} — ${matrix.tenant_name}`}
          action={L("المستخدم × القناة", "User × channel")}
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {matrix.providers.map((provider) => (
              <span key={provider.provider} className="inline-flex items-center gap-1 rounded-md bg-surface px-2 py-1 text-[11.5px]">
                {provider.connected ? <CheckCircle2 className="h-3 w-3 text-success" /> : <Lock className="h-3 w-3 text-muted-foreground" />}
                {provider.display_name}
              </span>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-border text-[10.5px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 text-start font-medium">{L("المستخدم", "User")}</th>
                  {matrix.providers.map((provider) => (
                    <th key={provider.provider} className="px-2 py-2 text-center font-medium">
                      {provider.display_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.members.map((member) => (
                  <tr key={member.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2.5">
                      <div className="font-medium">{member.full_name || member.email}</div>
                      <div className="text-[10.5px] text-muted-foreground">{member.role_code} · {member.email}</div>
                    </td>
                    {matrix.providers.map((provider) => {
                      const row = accessMap.get(`${member.id}:${provider.provider}`);
                      const enabled = row ? row.enabled : true;
                      const key = `${member.id}:${provider.provider}`;
                      return (
                        <td key={provider.provider} className="px-2 py-2 text-center">
                          <button
                            type="button"
                            disabled={savingCell === key}
                            onClick={() => onToggle(member, provider.provider, !enabled)}
                            className={cn(
                              "inline-flex h-7 w-7 items-center justify-center rounded-md border transition-colors",
                              enabled
                                ? "border-success/30 bg-success/10 text-success hover:bg-success/20"
                                : "border-border bg-surface text-muted-foreground hover:bg-card"
                            )}
                            title={enabled ? L("مسموح — اضغط للإيقاف", "Enabled — click to disable") : L("مقفول — اضغط للتفعيل", "Disabled — click to enable")}
                          >
                            {enabled ? <Unlock className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {L(
              "القفل هنا يخص ظهور القناة لهذا المستخدم في صندوق الوارد. فصل القناة نفسه يتم من إعدادات القنوات.",
              "This lock controls whether the channel appears for this user in the inbox. Disconnecting the channel itself stays in Channels settings."
            )}
          </p>
        </SectionCard>
      )}
    </div>
  );
}

function VisitorsTab({ L, data, summary }) {
  const items = data?.items || [];
  const series = summary?.series || [];
  const peak = Math.max(1, ...series.map((row) => row.events));
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <KpiCard label={L("إجمالي الأحداث", "Total events")} value={fmt(data?.total)} sub={L("آخر 24 ساعة", "last 24h")} to="/owner" />
        <KpiCard label={L("زوار فريدون", "Unique visitors")} value={fmt(data?.unique_visitors)} sub={L("آخر 24 ساعة", "last 24h")} to="/owner" />
        <KpiCard label={L("أكثر صفحة", "Top page")} value={data?.top_paths?.[0]?.path || "—"} sub={fmt(data?.top_paths?.[0]?.count)} to="/owner" />
      </div>
      {series.length > 0 && (
        <SectionCard title={L("الحدث بالساعة (24 ساعة)", "Events by hour (24h)")}>
          <div className="flex items-end gap-1.5" dir="ltr">
            {series.map((row) => (
              <div
                key={row.bucket}
                title={`${row.bucket.slice(11, 16)} — ${row.events} events / ${row.errors} errors`}
                className="flex-1 rounded-t bg-primary/25"
                style={{ height: `${Math.max(6, Math.round((row.events / peak) * 72))}px` }}
              />
            ))}
          </div>
          <div className="mt-2 grid gap-3 text-[12px] text-muted-foreground sm:grid-cols-3">
            <span>
              {L("معدل الأخطاء", "Error rate")}:{" "}
              <span className="font-medium text-foreground">{((summary?.error_rate || 0) * 100).toFixed(1)}%</span>
            </span>
            <span>
              {L("زمن التحميل p50", "Load p50")}:{" "}
              <span className="font-medium text-foreground">{summary?.perf_p50_ms != null ? `${summary.perf_p50_ms} ms` : "—"}</span>
            </span>
            <span>
              {L("زمن التحميل p95", "Load p95")}:{" "}
              <span className="font-medium text-foreground">{summary?.perf_p95_ms != null ? `${summary.perf_p95_ms} ms` : "—"}</span>
            </span>
          </div>
        </SectionCard>
      )}
      <SectionCard title={L("أحداث الزوار", "Visitor events")}>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-border text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <th className="py-2 text-start font-medium">{L("الحدث", "Event")}</th>
                <th className="py-2 text-start font-medium">{L("الصفحة", "Path")}</th>
                <th className="py-2 text-start font-medium">{L("الزائر", "Visitor")}</th>
                <th className="py-2 text-start font-medium">{L("التفاصيل", "Detail")}</th>
                <th className="py-2 text-end font-medium">{L("الوقت", "Time")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((event) => (
                <tr key={event.id} className="border-b border-border/60 last:border-0">
                  <td className="py-2.5">
                    <Badge tone={event.event_type === "error" ? "destructive" : event.event_type === "click" ? "primary" : "muted"}>
                      {event.event_type}
                    </Badge>
                  </td>
                  <td className="max-w-[260px] truncate py-2.5">{event.path}</td>
                  <td className="py-2.5 font-mono text-[10.5px] text-muted-foreground">{event.visitor_id.slice(0, 8)}</td>
                  <td className="max-w-[260px] truncate py-2.5 text-muted-foreground">
                    {event.element || (event.duration_ms != null ? `${event.duration_ms} ms` : event.status_code || "—")}
                  </td>
                  <td className="py-2.5 text-end text-[11px] text-muted-foreground">{time(event.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div className="py-10 text-center text-[13px] text-muted-foreground">
              {L("لا توجد أحداث بعد. افتح الموقع العام وسجّل زيارة.", "No events yet. Open the public site and record a visit.")}
            </div>
          )}
        </div>
      </SectionCard>
    </div>
  );
}

function SystemTab({ L, data }) {
  const tone = TONE[data?.status] || "muted";
  const outbox = data?.outbox || {};
  const deliveries = data?.webhook_deliveries || {};
  const ingress = data?.webhook_ingress || {};
  const visitors = data?.visitors || {};
  const age = (seconds) => {
    if (seconds == null) return L("لا يوجد", "none");
    if (seconds < 90) return `${seconds}s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Badge tone={tone}>{data?.status || "—"}</Badge>
        <span className="text-[11.5px] text-muted-foreground">{time(data?.generated_at)}</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <SectionCard title={L("طابور الأحداث (Outbox)", "Event backlog (Outbox)")}>
          <dl className="space-y-2 text-[12.5px]">
            <Row label={L("في الانتظار", "Pending")} value={fmt(outbox.pending)} />
            <Row label={L("فاشلة", "Failed")} value={fmt(outbox.failed)} />
            <Row
              label={L("أقدم صف معلّق", "Oldest pending")}
              value={age(outbox.oldest_pending_age_seconds)}
            />
          </dl>
        </SectionCard>
        <SectionCard title={L("تسليمات الويب هوك", "Webhook deliveries")}>
          <dl className="space-y-2 text-[12.5px]">
            <Row label={L("في الطابور", "Queued")} value={fmt(deliveries.queued)} />
            <Row label={L("فاشلة", "Failed")} value={fmt(deliveries.failed)} />
            <Row label={L("ماتة", "Dead")} value={fmt(deliveries.dead)} />
            <Row
              label={L("أقدم صف في الطابور", "Oldest queued")}
              value={age(deliveries.oldest_queued_age_seconds)}
            />
          </dl>
        </SectionCard>
        <SectionCard title={L("استقبال الويب هوك (24 ساعة)", "Webhook ingress (24h)")}>
          <dl className="space-y-2 text-[12.5px]">
            <Row label={L("فاشلة/ماتة", "Failed / dead")} value={fmt(ingress.failed_24h)} />
          </dl>
        </SectionCard>
        <SectionCard title={L("سلوك الزوار (24 ساعة)", "Visitor behavior (24h)")}>
          <dl className="space-y-2 text-[12.5px]">
            <Row label={L("أحداث", "Events")} value={fmt(visitors.events_24h)} />
            <Row label={L("أخطاء", "Errors")} value={fmt(visitors.errors_24h)} />
            <Row label={L("معدل الأخطاء", "Error rate")} value={`${((visitors.error_rate || 0) * 100).toFixed(1)}%`} />
          </dl>
        </SectionCard>
      </div>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{value}</dd>
    </div>
  );
}

function SpendCell({ L, tenant }) {
  // Money crosses the wire as Decimal STRINGS on purpose (ADR-053) — derive
  // the ratio from the strings' numeric values at render, never store floats.
  const spend = Number(tenant.ai_spend || "0");
  const cap = Number(tenant.ai_cap || "0");
  const ratio = cap > 0 ? (spend / cap) * 100 : 0;
  // Same thresholds the runtime's own alerts fire at: 50 / 80 / 90 / 100.
  const tone = ratio >= 90 ? "destructive" : ratio >= 80 ? "warning" : ratio >= 50 ? "primary" : "muted";
  const barTone =
    ratio >= 90 ? "bg-destructive" : ratio >= 80 ? "bg-warning" : ratio >= 50 ? "bg-primary" : "bg-emerald-500/60";
  return (
    <div className="min-w-36" title={`${tenant.ai_on_exceed} · ${tenant.ai_cap_source}`}>
      <div className="flex items-center justify-between gap-2 text-[11.5px] tabular-nums">
        <span className="font-medium">{spend.toFixed(2)}</span>
        <span className="text-muted-foreground">/ {cap.toFixed(0)}</span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface">
        <div
          className={`h-full rounded-full ${barTone}`}
          style={{ width: `${Math.min(100, Math.max(ratio > 0 ? 4 : 0, ratio))}%` }}
        />
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
        <span>{ratio.toFixed(0)}%</span>
        {tenant.ai_failed_runs_24h > 0 && (
          <Badge tone="warning">
            {L("فشل 24س", "failed 24h")}: {tenant.ai_failed_runs_24h}
          </Badge>
        )}
        {tenant.ai_on_exceed === "warn" && <Badge tone="muted">{L("تحذير فقط", "warn only")}</Badge>}
      </div>
      <span className="sr-only">{L("نسبة الصرف", "spend ratio")}: <Badge tone={tone}>{ratio.toFixed(0)}%</Badge></span>
    </div>
  );
}
