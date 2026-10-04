import React, { useEffect, useMemo, useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/dashboardData";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import CustomerDrawer from "@/components/customers/CustomerDrawer";

export default function Customers() {
  const t = useT();
  const [query, setQuery] = useState("");
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
    api("/customers?limit=100")
      .then((response) => {
        if (!alive) return;
        setCustomers(response?.items || []);
        setNextCursor(response?.next_cursor || null);
      })
      .catch((e) => alive && setError(e?.message || "Could not load customers."))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [reloadAttempt]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (customers || []).filter((customer) =>
      !needle || [customer.name, customer.phone, customer.email]
        .some((value) => String(value || "").toLowerCase().includes(needle))
    );
  }, [customers, query]);

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
      setError(e?.message || "Could not load more customers.");
    } finally {
      setLoadingMore(false);
    }
  }

  const STATUS = {
    blocked: { label: t("customers.status.blocked", "Blocked"), tone: "destructive" },
    unknown: { label: t("common.unavailable", "—"), tone: "muted" },
  };

  return (
    <div>
      <PageHeader title={t("customers.title")} subtitle={t("customers.subtitle")} actions={
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("customers.search")}
            placeholder={t("customers.search")}
            className="h-9 w-56 pl-9 pr-3 rounded-lg bg-card border border-border text-[13px] placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring/30"
          />
        </div>
      } />

      {error && <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <span>{error}</span>
        {customers === null ? (
          <button type="button" onClick={() => setReloadAttempt((attempt) => attempt + 1)} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
        ) : nextCursor ? (
          <button type="button" onClick={loadMore} disabled={loadingMore} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
        ) : null}
      </div>}

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] table-fixed text-left">
            <colgroup><col style={{ width: "34%" }} /><col style={{ width: "27%" }} /><col style={{ width: "21%" }} /><col style={{ width: "18%" }} /></colgroup>
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-medium px-5 py-3">{t("customers.col.customer")}</th>
                <th className="font-medium px-5 py-3">{t("customers.detail.identified")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("customers.col.ltv")}</th>
                <th className="font-medium px-5 py-3">{t("customers.col.status")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((customer) => {
                const status = customer.is_blocked ? "blocked" : "unknown";
                const badge = STATUS[status];
                return (
                  <tr key={customer.id} className="hover:bg-surface/50 transition-colors">
                    <td className="px-5 py-3">
                      <button type="button" onClick={() => setSelected(customer)} className="flex items-center gap-3 text-left">
                        <span className="h-9 w-9 rounded-full bg-accent/15 text-accent grid place-items-center text-[12px] font-semibold">
                          {String(customer.name || "—").trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}
                        </span>
                        <span className="text-[13.5px] font-medium">{customer.name}</span>
                      </button>
                    </td>
                    <td className="px-5 py-3 text-[12.5px] text-muted-foreground" dir="auto">{customer.phone || customer.email || "—"}</td>
                    <td className="px-5 py-3 text-right text-[13.5px] font-semibold tabular-nums">{formatCurrency(Number(customer.lifetime_value || 0))}</td>
                    <td className="px-5 py-3"><Badge tone={badge.tone}>{badge.label}</Badge></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {customers === null && loading && <div className="py-12 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        {customers !== null && filtered.length === 0 && <div className="py-12 text-center text-[13.5px] text-muted-foreground">{query ? t("customers.empty", { q: query }) : t("customers.none")}</div>}
        {nextCursor && customers !== null && (
          <div className="border-t border-border p-3 text-center">
            <button type="button" onClick={loadMore} disabled={loadingMore} className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface disabled:opacity-60">
              {loadingMore && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("common.loadMore", "Load more")}
            </button>
          </div>
        )}
      </div>

      <CustomerDrawer customer={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
