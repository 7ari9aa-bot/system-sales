import React from "react";
import { Plus, Users, Archive, Power } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/regional";
import useCustomers from "@/hooks/useCustomers";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";

const ruleDefinitions = {
  repeat: (value) => ({ field: "orders_count", op: "gte", value: Number(value) }),
  value: (value) => ({ field: "lifetime_value", op: "gte", value: Number(value) }),
  email: () => ({ field: "has_email", op: "eq", value: true }),
  phone: () => ({ field: "has_phone", op: "eq", value: true }),
};

export default function Audience() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const { customers, loading: loadingCustomers, loadingMore, nextCursor, loadMore, reload: reloadCustomers, error: customerError } = useCustomers();
  const [segments, setSegments] = React.useState(null);
  const [loadingSegments, setLoadingSegments] = React.useState(true);
  const [segmentError, setSegmentError] = React.useState("");
  const [formOpen, setFormOpen] = React.useState(false);
  const [segmentName, setSegmentName] = React.useState("");
  const [rule, setRule] = React.useState("repeat");
  const [threshold, setThreshold] = React.useState("2");
  const [saving, setSaving] = React.useState(false);
  const [busySegment, setBusySegment] = React.useState("");
  const [knownCounts, setKnownCounts] = React.useState({});

  const loadSegments = React.useCallback(async () => {
    setLoadingSegments(true);
    try {
      const rows = await api("/segments");
      setSegments(Array.isArray(rows) ? rows : []);
      setSegmentError("");
    } catch (error) {
      setSegmentError(error?.message || (isAr ? "تعذر تحميل شرائح الجمهور" : "Could not load audience segments"));
    } finally {
      setLoadingSegments(false);
    }
  }, [isAr]);

  React.useEffect(() => { void loadSegments(); }, [loadSegments]);

  const activeCount = (segments || []).filter((segment) => segment.is_active).length;

  async function createSegment(event) {
    event.preventDefault();
    const numericThreshold = Number(threshold);
    if (!segmentName.trim() || !Number.isFinite(numericThreshold) || numericThreshold < 0) return;
    setSaving(true);
    setSegmentError("");
    try {
      const condition = ruleDefinitions[rule](numericThreshold);
      const definition = { all: [condition] };
      const preview = await api("/segments/preview", { method: "POST", body: { definition, sample_limit: 0 } });
      const created = await api("/segments", {
        method: "POST",
        body: { name: segmentName.trim(), definition },
      });
      setKnownCounts((current) => ({ ...current, [created.id]: preview.count }));
      setSegments((current) => [created, ...(current || [])]);
      setSegmentName("");
      setFormOpen(false);
    } catch (error) {
      setSegmentError(error?.message || (isAr ? "تعذر إنشاء الشريحة" : "Could not create the segment"));
    } finally {
      setSaving(false);
    }
  }

  async function toggleSegment(segment) {
    setBusySegment(segment.id);
    setSegmentError("");
    try {
      const updated = await api(`/segments/${segment.id}`, {
        method: "PUT",
        body: { is_active: !segment.is_active },
      });
      setSegments((rows) => (rows || []).map((row) => row.id === segment.id ? updated : row));
    } catch (error) {
      setSegmentError(error?.message || (isAr ? "تعذر تحديث الشريحة" : "Could not update segment"));
    } finally {
      setBusySegment("");
    }
  }

  async function archiveSegment(segment) {
    const confirmed = window.confirm(isAr ? `أرشفة شريحة «${segment.name}»؟` : `Archive the “${segment.name}” segment?`);
    if (!confirmed) return;
    setBusySegment(segment.id);
    setSegmentError("");
    try {
      await api(`/segments/${segment.id}`, { method: "DELETE" });
      setSegments((rows) => (rows || []).map((row) => row.id === segment.id ? { ...row, is_active: false } : row));
    } catch (error) {
      setSegmentError(error?.message || (isAr ? "تعذر أرشفة الشريحة" : "Could not archive segment"));
    } finally {
      setBusySegment("");
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-[15px] font-semibold">{t("marketing.audience.segments")}</h2>
          <p className="mt-1 text-[12px] text-muted-foreground">{isAr ? "شرائح محفوظة بقواعد فعلية قابلة للمعاينة." : "Saved audience rules with server-side preview counts."}</p>
        </div>
        <Button type="button" onClick={() => setFormOpen((open) => !open)} className="gap-1.5"><Plus className="h-4 w-4" />{t("marketing.audience.newSegment")}</Button>
      </div>

      {segmentError && <div role="alert" className="mb-3 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{segmentError}</div>}

      {formOpen && (
        <form onSubmit={createSegment} className="mb-4 grid gap-3 rounded-2xl border border-border bg-card p-4 sm:grid-cols-[1fr_1fr_160px_auto] sm:items-end">
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">{isAr ? "اسم الشريحة" : "Segment name"}<Input required maxLength={255} value={segmentName} onChange={(event) => setSegmentName(event.target.value)} /></label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">
            {isAr ? "قاعدة الشريحة" : "Rule"}
            <select value={rule} onChange={(event) => { setRule(event.target.value); setThreshold(event.target.value === "repeat" ? "2" : "1000"); }} className="h-9 rounded-md border border-input bg-background px-3 text-[13px] text-foreground">
              <option value="repeat">{isAr ? "عدد الطلبات على الأقل" : "Minimum order count"}</option>
              <option value="value">{isAr ? "قيمة العميل على الأقل" : "Minimum lifetime value"}</option>
              <option value="email">{isAr ? "لديه بريد إلكتروني" : "Has an email address"}</option>
              <option value="phone">{isAr ? "لديه رقم هاتف" : "Has a phone number"}</option>
            </select>
          </label>
          {(rule === "repeat" || rule === "value") ? (
            <label className="grid gap-1.5 text-[12px] text-muted-foreground">{rule === "repeat" ? (isAr ? "الحد الأدنى" : "Minimum") : (isAr ? "الحد الأدنى للقيمة" : "Minimum value")}<Input type="number" min="0" step={rule === "repeat" ? "1" : "0.01"} required value={threshold} onChange={(event) => setThreshold(event.target.value)} /></label>
          ) : <div className="hidden sm:block" />}
          <Button type="submit" disabled={saving || !segmentName.trim()}>{saving ? "…" : (isAr ? "معاينة وحفظ" : "Preview and save")}</Button>
        </form>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3.5 sm:max-w-md">
        <SummaryCard icon={Users} label={isAr ? "الشرائح المحفوظة" : "Saved segments"} value={loadingSegments ? "…" : (segments || []).length} />
        <SummaryCard icon={Power} label={isAr ? "الشرائح النشطة" : "Active segments"} value={loadingSegments ? "…" : activeCount} />
      </div>

      {loadingSegments && segments == null ? (
        <div className="rounded-2xl border border-border bg-card py-10 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل الشرائح…" : "Loading segments…"}</div>
      ) : segments == null && segmentError ? (
        <div className="rounded-2xl border border-border bg-card py-8 text-center text-[13px] text-muted-foreground">
          <p>{isAr ? "تعذر تحميل الشرائح." : "Segments could not be loaded."}</p>
          <Button type="button" variant="outline" onClick={() => void loadSegments()} className="mt-3">{isAr ? "إعادة المحاولة" : "Retry"}</Button>
        </div>
      ) : segments != null && segments.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card py-10 text-center text-[13px] text-muted-foreground">{isAr ? "لا توجد شرائح محفوظة." : "No saved segments."}</div>
      ) : (
        <div className="mb-7 grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          {segments.map((segment) => {
            const count = knownCounts[segment.id] ?? segment.last_count;
            return (
              <div key={segment.id} className="rounded-2xl border border-border bg-card p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[13.5px] font-semibold">{segment.name}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground">{segment.is_active ? (isAr ? "نشطة" : "Active") : (isAr ? "غير نشطة" : "Inactive")}</div>
                  </div>
                  <Badge tone={segment.is_active ? "success" : "muted"}>{count == null ? "—" : Number(count).toLocaleString()}</Badge>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2 border-t border-border pt-3">
                  <span className="text-[11px] text-muted-foreground">{count == null ? (isAr ? "لم تُحسب المطابقة" : "Audience not evaluated") : (isAr ? "عميل مطابق" : "matching customers")}</span>
                  <div className="flex gap-1">
                    <button type="button" disabled={busySegment === segment.id} onClick={() => toggleSegment(segment)} title={segment.is_active ? (isAr ? "إيقاف" : "Deactivate") : (isAr ? "تفعيل" : "Activate")} className="grid h-8 w-8 place-items-center rounded-lg hover:bg-surface disabled:opacity-50"><Power className="h-4 w-4" /></button>
                    {segment.is_active && <button type="button" disabled={busySegment === segment.id} onClick={() => archiveSegment(segment)} title={isAr ? "أرشفة" : "Archive"} className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground hover:bg-surface disabled:opacity-50"><Archive className="h-4 w-4" /></button>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <h2 className="mb-3 font-display text-[15px] font-semibold">{t("marketing.audience.contacts")}</h2>
      {customerError && <div role="alert" className="mb-3 text-[12px] text-destructive">{customerError}</div>}
      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left">
            <thead><tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
              <th className="px-5 py-3 font-medium">{t("customers.col.customer")}</th>
              <th className="px-5 py-3 font-medium">{isAr ? "وسيلة التواصل" : "Contact"}</th>
              <th className="px-5 py-3 text-right font-medium">{t("customers.col.ltv")}</th>
              <th className="px-5 py-3 font-medium">{t("customers.col.status")}</th>
            </tr></thead>
            <tbody className="divide-y divide-border">
              {loadingCustomers && customers == null ? (
                <tr><td colSpan="4" className="py-8 text-center text-[12.5px] text-muted-foreground">{isAr ? "جارٍ تحميل العملاء…" : "Loading customers…"}</td></tr>
              ) : customers == null && customerError ? (
                <tr><td colSpan="4" className="py-8 text-center text-[12.5px] text-muted-foreground">
                  <span>{isAr ? "تعذر تحميل العملاء." : "Customers could not be loaded."}</span>
                  <Button type="button" variant="outline" onClick={() => void reloadCustomers()} className="ml-3">{isAr ? "إعادة المحاولة" : "Retry"}</Button>
                </td></tr>
              ) : (customers || []).length === 0 ? (
                <tr><td colSpan="4" className="py-8 text-center text-[12.5px] text-muted-foreground">{isAr ? "لا يوجد عملاء." : "No customers."}</td></tr>
              ) : customers.map((customer) => (
                <tr key={customer.id} className="hover:bg-surface/50">
                  <td className="px-5 py-3 text-[13px] font-medium">{customer.name}</td>
                  <td className="px-5 py-3 text-[12px] text-muted-foreground">{customer.email || customer.phone || "—"}</td>
                  <td className="px-5 py-3 text-right text-[13px] font-semibold tabular-nums">{formatCurrency(Number(customer.lifetime_value || 0))}</td>
                  <td className="px-5 py-3"><Badge tone={customer.is_blocked ? "destructive" : "primary"}>{customer.is_blocked ? (isAr ? "محظور" : "Blocked") : (isAr ? "متاح" : "Available")}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {nextCursor && <div className="border-t border-border p-3 text-center"><Button type="button" variant="outline" disabled={loadingMore} onClick={loadMore}>{loadingMore ? "…" : (isAr ? "تحميل المزيد" : "Load more")}</Button></div>}
      </div>
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value }) {
  return <div className="rounded-2xl border border-border bg-card p-4"><div className="flex items-center gap-2 text-[12px] text-muted-foreground"><Icon className="h-4 w-4" />{label}</div><div className="mt-2 font-display text-[22px] font-semibold tabular-nums">{value}</div></div>;
}
