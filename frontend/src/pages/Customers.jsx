import React, { useEffect, useMemo, useState } from "react";
import {
  Search,
  Loader2,
  Users,
  Sparkles,
  TrendingUp,
  CreditCard,
  MessageCircle,
  ArrowUpDown,
  Filter,
  Inbox,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/dashboardData";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import CustomerDrawer from "@/components/customers/CustomerDrawer";
import { cn } from "@/lib/utils";

export default function Customers() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [filterSegment, setFilterSegment] = useState("all"); // all | vip | active | blocked | has_phone
  const [sortBy, setSortBy] = useState("ltv_desc"); // ltv_desc | newest | name_asc
  const [customers, setCustomers] = useState(null);
  const [selected, setSelected] = useState(null);
  const [nextCursor, setNextCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reloadAttempt, setReloadAttempt] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    api("/customers?limit=150")
      .then((response) => {
        if (!alive) return;
        setCustomers(response?.items || []);
        setNextCursor(response?.next_cursor || null);
      })
      .catch((e) => alive && setError(e?.message || (isAr ? "تعذر تحميل قائمة العملاء." : "Could not load customers.")))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [reloadAttempt, isAr]);

  // Handle local customer updates from drawer (e.g. block/unblock)
  function handleCustomerUpdated(updated) {
    setCustomers((prev) =>
      (prev || []).map((c) => (c.id === updated.id ? { ...c, ...updated } : c))
    );
    if (selected?.id === updated.id) {
      setSelected((prev) => ({ ...prev, ...updated }));
    }
  }

  // Summary Metrics
  const metrics = useMemo(() => {
    const list = customers || [];
    const total = list.length;
    const active = list.filter((c) => !c.is_blocked).length;
    const blocked = list.filter((c) => c.is_blocked).length;
    const totalLtv = list.reduce((sum, c) => sum + (Number(c.lifetime_value) || 0), 0);
    const avgLtv = total > 0 ? totalLtv / total : 0;
    const vips = list.filter((c) => (Number(c.lifetime_value) || 0) >= 1000).length;
    return { total, active, blocked, totalLtv, avgLtv, vips };
  }, [customers]);

  // Filtered and Sorted list
  const filtered = useMemo(() => {
    let list = customers || [];
    const needle = query.trim().toLowerCase();

    if (needle) {
      list = list.filter((c) =>
        [c.name, c.phone, c.email]
          .some((v) => String(v || "").toLowerCase().includes(needle))
      );
    }

    if (filterSegment === "vip") {
      list = list.filter((c) => (Number(c.lifetime_value) || 0) >= 1000);
    } else if (filterSegment === "active") {
      list = list.filter((c) => !c.is_blocked);
    } else if (filterSegment === "blocked") {
      list = list.filter((c) => c.is_blocked);
    } else if (filterSegment === "has_phone") {
      list = list.filter((c) => Boolean(c.phone));
    }

    // Sort
    return [...list].sort((a, b) => {
      if (sortBy === "ltv_desc") {
        return (Number(b.lifetime_value) || 0) - (Number(a.lifetime_value) || 0);
      }
      if (sortBy === "newest") {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      }
      if (sortBy === "name_asc") {
        return String(a.name || "").localeCompare(String(b.name || ""));
      }
      return 0;
    });
  }, [customers, query, filterSegment, sortBy]);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "100", cursor: nextCursor });
      const response = await api(`/customers?${params.toString()}`);
      setCustomers((previous) => [...(previous || []), ...(response?.items || [])]);
      setNextCursor(response?.next_cursor || null);
    } catch (e) {
      setError(e?.message || (isAr ? "تعذر تحميل المزيد من العملاء." : "Could not load more customers."));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title={isAr ? "قاعدة العملاء (CRM)" : t("customers.title")}
        subtitle={isAr ? "سجل شامل لكل من تواصل واشترى من متجرك عبر الكاشير والقنوات." : t("customers.subtitle")}
      />

      {/* Top Rich Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-3.5 shadow-2xs">
          <span className="h-11 w-11 rounded-xl bg-primary/10 text-primary grid place-items-center shrink-0">
            <Users className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="text-[12px] text-muted-foreground">{isAr ? "إجمالي العملاء" : "Total Customers"}</div>
            <div className="font-display text-[22px] font-bold text-foreground tabular-nums mt-0.5">
              {metrics.total}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-3.5 shadow-2xs">
          <span className="h-11 w-11 rounded-xl bg-amber-500/15 text-amber-600 grid place-items-center shrink-0">
            <Sparkles className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="text-[12px] text-muted-foreground">{isAr ? "عملاء VIP" : "VIP Spenders"}</div>
            <div className="font-display text-[22px] font-bold text-foreground tabular-nums mt-0.5">
              {metrics.vips}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-3.5 shadow-2xs">
          <span className="h-11 w-11 rounded-xl bg-emerald-500/15 text-emerald-600 grid place-items-center shrink-0">
            <TrendingUp className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="text-[12px] text-muted-foreground">{isAr ? "إجمالي الإنفاق (LTV)" : "Total LTV"}</div>
            <div className="font-display text-[20px] font-bold text-foreground tabular-nums mt-0.5">
              {formatCurrency(metrics.totalLtv)}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-4 flex items-center gap-3.5 shadow-2xs">
          <span className="h-11 w-11 rounded-xl bg-blue-500/15 text-blue-600 grid place-items-center shrink-0">
            <CreditCard className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="text-[12px] text-muted-foreground">{isAr ? "متوسط قيمة العميل" : "Avg LTV"}</div>
            <div className="font-display text-[20px] font-bold text-foreground tabular-nums mt-0.5">
              {formatCurrency(metrics.avgLtv)}
            </div>
          </div>
        </div>
      </div>

      {/* Toolbar & Filters */}
      <div className="rounded-2xl border border-border bg-card p-4 space-y-3 shadow-2xs">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label={t("customers.search")}
              placeholder={isAr ? "ابحث بالاسم، رقم الهاتف، أو البريد الإلكتروني…" : t("customers.search")}
              className="h-9 w-full pl-9 pr-3 rounded-xl bg-surface border border-border text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
          </div>

          {/* Sort selection */}
          <div className="flex items-center gap-2 shrink-0">
            <ArrowUpDown className="h-4 w-4 text-muted-foreground shrink-0" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="h-9 rounded-xl border border-border bg-surface px-3 text-[12.5px] font-medium text-foreground outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="ltv_desc">{isAr ? "الأعلى إنفاقاً أولاً" : "Highest LTV"}</option>
              <option value="newest">{isAr ? "الأحدث تسجيلاً" : "Newest"}</option>
              <option value="name_asc">{isAr ? "الترتيب الأبجدي (أ - ي)" : "Name (A - Z)"}</option>
            </select>
          </div>
        </div>

        {/* Filter Segment Tabs */}
        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-border/60">
          <span className="text-[12px] text-muted-foreground me-2 font-medium flex items-center gap-1">
            <Filter className="h-3.5 w-3.5" />
            <span>{isAr ? "تصفية:" : "Filter:"}</span>
          </span>
          {[
            { id: "all", label: isAr ? "جميع العملاء" : "All" },
            { id: "vip", label: isAr ? "⭐ كبار العملاء (VIP)" : "⭐ VIP" },
            { id: "active", label: isAr ? "النشطين" : "Active" },
            { id: "blocked", label: isAr ? "المحظورين" : "Blocked" },
            { id: "has_phone", label: isAr ? "لديهم هاتف مسجل" : "With Phone" },
          ].map((seg) => (
            <button
              key={seg.id}
              type="button"
              onClick={() => setFilterSegment(seg.id)}
              className={cn(
                "px-3 py-1 rounded-lg text-[12px] font-medium transition-colors",
                filterSegment === seg.id
                  ? "bg-primary text-primary-foreground font-semibold"
                  : "bg-surface hover:bg-surface/80 text-muted-foreground hover:text-foreground border border-border/60"
              )}
            >
              {seg.label}
            </button>
          ))}
          <span className="ms-auto text-[11.5px] text-muted-foreground">
            {isAr ? `عرض ${filtered.length} من أصل ${metrics.total}` : `Showing ${filtered.length} of ${metrics.total}`}
          </span>
        </div>
      </div>

      {error && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setReloadAttempt((a) => a + 1)}
            className="shrink-0 font-semibold underline hover:opacity-80"
          >
            {isAr ? "إعادة المحاولة" : "Retry"}
          </button>
        </div>
      )}

      {/* Rich Table */}
      <div className="rounded-2xl bg-card border border-border overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] table-fixed text-left">
            <colgroup>
              <col style={{ width: "32%" }} />
              <col style={{ width: "24%" }} />
              <col style={{ width: "16%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "14%" }} />
            </colgroup>
            <thead>
              <tr className="border-b border-border bg-surface/40 text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-semibold px-5 py-3.5 text-start">{t("customers.col.customer")}</th>
                <th className="font-semibold px-5 py-3.5 text-start">{isAr ? "بيانات التواصل" : "Contact"}</th>
                <th className="font-semibold px-5 py-3.5 text-right">{t("customers.col.ltv")}</th>
                <th className="font-semibold px-5 py-3.5 text-center">{t("customers.col.status")}</th>
                <th className="font-semibold px-5 py-3.5 text-center">{isAr ? "إجراءات" : "Actions"}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((customer) => {
                const ltvVal = Number(customer.lifetime_value || 0);
                const isVipCust = ltvVal >= 1000;
                const isBlockedCust = Boolean(customer.is_blocked);

                return (
                  <tr key={customer.id} className="hover:bg-surface/50 transition-colors group">
                    {/* Customer Name & Avatar */}
                    <td className="px-5 py-3.5 text-start">
                      <button
                        type="button"
                        onClick={() => setSelected(customer)}
                        className="flex items-center gap-3 text-start w-full group/btn"
                      >
                        <span className="h-10 w-10 rounded-2xl bg-primary/10 text-primary grid place-items-center text-[13px] font-bold shrink-0 transition-transform group-hover/btn:scale-105">
                          {String(customer.name || "—").trim().split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase()}
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[14px] font-semibold text-foreground group-hover/btn:text-primary transition-colors truncate">
                              {customer.name || (isAr ? "عميل بدون اسم" : "Unnamed")}
                            </span>
                            {isVipCust && (
                              <span title="VIP Customer" className="text-amber-500 shrink-0 text-[11px]">★</span>
                            )}
                          </div>
                          <div className="text-[11.5px] text-muted-foreground flex items-center gap-2 mt-0.5">
                            <span>ID: {String(customer.id).slice(0, 8)}</span>
                          </div>
                        </div>
                      </button>
                    </td>

                    {/* Contact */}
                    <td className="px-5 py-3.5 text-start" dir="ltr">
                      <div className="text-[12.5px] font-medium text-foreground truncate">
                        {customer.phone || customer.email || "—"}
                      </div>
                      {customer.phone && customer.email && (
                        <div className="text-[11px] text-muted-foreground truncate">{customer.email}</div>
                      )}
                    </td>

                    {/* LTV */}
                    <td className="px-5 py-3.5 text-right font-display text-[14px] font-bold text-foreground tabular-nums">
                      {formatCurrency(ltvVal)}
                    </td>

                    {/* Status */}
                    <td className="px-5 py-3.5 text-center">
                      {isBlockedCust ? (
                        <Badge tone="destructive">{isAr ? "محظور" : "Blocked"}</Badge>
                      ) : (
                        <Badge tone="success">{isAr ? "نشط" : "Active"}</Badge>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="px-5 py-3.5 text-center">
                      <div className="flex items-center justify-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => setSelected(customer)}
                          className="h-8 px-2.5 rounded-lg border border-border bg-card hover:bg-surface text-[11.5px] font-semibold text-foreground transition-colors"
                        >
                          {isAr ? "البروفايل والسجل" : "360 Profile"}
                        </button>
                        {customer.phone && (
                          <a
                            href={`https://wa.me/${customer.phone.replace(/[^0-9]/g, "")}`}
                            target="_blank"
                            rel="noreferrer"
                            title={isAr ? "محادثة واتساب" : "WhatsApp Chat"}
                            className="h-8 w-8 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-600 grid place-items-center transition-colors"
                          >
                            <MessageCircle className="h-4 w-4" />
                          </a>
                        )}
                        <button
                          type="button"
                          onClick={() => navigate("/inbox")}
                          title={isAr ? "الانتقال إلى المحادثات" : "Go to Inbox"}
                          className="h-8 w-8 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary grid place-items-center transition-colors"
                        >
                          <Inbox className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {customers === null && loading && (
          <div className="py-16 grid place-items-center text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        )}

        {customers !== null && filtered.length === 0 && (
          <div className="py-16 text-center space-y-2">
            <Users className="h-8 w-8 mx-auto text-muted-foreground/50" />
            <div className="text-[14px] font-semibold text-foreground">
              {query ? (isAr ? `لا يوجد عملاء يطابقون "${query}"` : t("customers.empty", { q: query })) : (isAr ? "لا يوجد عملاء في هذه الفئة" : t("customers.none"))}
            </div>
            <p className="text-[12px] text-muted-foreground">
              {isAr ? "جرّب تغيير كلمات البحث أو تغيير تصنيف الفلتر أعلاه." : "Try adjusting your search or filters."}
            </p>
          </div>
        )}

        {nextCursor && customers !== null && (
          <div className="border-t border-border p-3.5 text-center">
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="inline-flex items-center gap-2 rounded-xl border border-border px-4 py-2 text-[13px] font-medium hover:bg-surface disabled:opacity-60 transition-colors"
            >
              {loadingMore && <Loader2 className="h-4 w-4 animate-spin" />}
              {isAr ? "تحميل المزيد من العملاء" : t("common.loadMore", "Load more")}
            </button>
          </div>
        )}
      </div>

      {/* Customer 360 Drawer */}
      <CustomerDrawer
        customer={selected}
        onClose={() => setSelected(null)}
        onCustomerUpdated={handleCustomerUpdated}
      />
    </div>
  );
}
