import React, { useMemo, useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, Search, DollarSign, ShoppingBag, TrendingUp, Loader2, X } from "lucide-react";
import { PageHeader, KpiCard } from "@/components/dashboard/ui";
import SalesWorkspace from "@/components/sales/SalesWorkspace";
import { formatCurrency } from "@/lib/dashboardData";
import useOrders from "@/hooks/useOrders";
import useSalesStats from "@/hooks/useSalesStats";
import { useDashboard } from "@/lib/dashboardContext";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const SALES_SECTIONS = new Map([["new", "new"], ["returns", "returns"], ["exchanges", "exchanges"]]);

function formatOrderMoney(value, currency) {
  if (currency) {
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value) || 0);
    } catch {
      // Fall through to the workspace formatter if the stored currency is invalid.
    }
  }
  return formatCurrency(Number(value) || 0);
}

function csvCell(value) {
  let text = String(value ?? "");
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export default function Orders() {
  const t = useT();
  const { range } = useDashboard();
  const live = useSalesStats(range);
  const orderState = useOrders();
  const orders = orderState.orders || [];
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [exporting, setExporting] = useState(false);
  const [pageError, setPageError] = useState(null);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [searchParams] = useSearchParams();

  const filters = useMemo(() => {
    const statuses = [...new Set(orders.map((order) => order.status).filter(Boolean))].sort();
    return [
      { id: "all", label: t("orders.filter.all") },
      ...statuses.map((status) => ({ id: status, label: t(`orders.status.${status}`, status) })),
    ];
  }, [orders, t]);

  const filtered = useMemo(() => orders.filter((order) => {
    const statusMatches = filter === "all" || order.status === filter;
    const needle = query.trim().toLowerCase();
    const queryMatches = !needle || `${order.customer} ${order.id} ${order.recordId}`.toLowerCase().includes(needle);
    return statusMatches && queryMatches;
  }), [orders, filter, query]);

  async function exportOrders() {
    setExporting(true);
    setPageError(null);
    try {
      const allRows = [];
      const seenCursors = new Set();
      let cursor = null;
      do {
        const params = new URLSearchParams({ limit: "200" });
        if (cursor) params.set("cursor", cursor);
        const response = await api(`/orders?${params.toString()}`);
        allRows.push(...(response?.items || []));
        cursor = response?.next_cursor || null;
        if (cursor && seenCursors.has(cursor)) throw new Error("The order export cursor repeated.");
        if (cursor) seenCursors.add(cursor);
      } while (cursor);

      const rows = [
        [t("orders.col.order"), t("orders.col.customer"), t("orders.col.status"), t("orders.col.total"), t("orders.col.date")],
        ...allRows.map((order) => [
          order.number ?? order.id,
          order.customer_id,
          order.status,
          order.grand_total,
          order.placed_at || order.created_at,
        ]),
      ];
      const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setPageError(e?.message || t("orders.export.error", "Could not export orders."));
    } finally {
      setExporting(false);
    }
  }

  const orderCount = live?.orders ?? null;
  const averageOrderValue = orderCount > 0 && live?.netSales != null ? Math.round(live.netSales / orderCount) : null;

  // ?s=new|returns|exchanges يفتح هيكل وحدة المبيعات؛ السجل هو نفس هذه القائمة.
  const salesSection = SALES_SECTIONS.get(searchParams.get("s"));
  if (salesSection) return <SalesWorkspace section={salesSection} />;

  return (
    <div>
      <PageHeader title={t("orders.title")} subtitle={t("orders.subtitle")} actions={
        <button type="button" onClick={exportOrders} disabled={exporting} className="h-9 px-3.5 rounded-lg bg-card border border-border text-[13px] font-medium flex items-center gap-1.5 hover:bg-surface disabled:opacity-60">
          {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {t("orders.export")}
        </button>
      } />

      {(pageError || orderState.error) && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <span>{pageError || orderState.error}</span>
          {orderState.error && <button type="button" disabled={orderState.loadingMore} onClick={() => void (orderState.nextCursor ? orderState.loadMore() : orderState.reload())} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>}
        </div>
      )}

      {orderState.customerError && (
        <div role="status" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-muted-foreground">
          <span>{t("orders.customerLookupError", "Customer names could not be loaded; order records are still available.")}</span>
          <button type="button" disabled={orderState.loading} onClick={orderState.reload} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5 mb-5">
        <KpiCard label={t("orders.kpi.netSales")} value={live?.netSales == null ? "—" : formatCurrency(live.netSales, true)} to="/orders" accent={{ icon: <DollarSign />, bg: "bg-primary/10", color: "text-primary" }} />
        <KpiCard label={t("orders.kpi.orders")} value={orderCount == null ? "—" : orderCount.toLocaleString()} to="/orders" accent={{ icon: <ShoppingBag />, bg: "bg-accent/10", color: "text-accent" }} />
        <KpiCard label={t("orders.kpi.aov")} value={averageOrderValue == null ? "—" : formatCurrency(averageOrderValue)} to="/orders" accent={{ icon: <TrendingUp />, bg: "bg-chart-4/10", color: "text-chart-4" }} />
      </div>

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="px-5 py-3 border-b border-border flex flex-col sm:flex-row gap-3 sm:items-center">
          <div className="flex gap-1 overflow-x-auto">
            {filters.map((item) => (
              <button key={item.id} type="button" aria-pressed={filter === item.id} onClick={() => setFilter(item.id)} className={cn("px-2.5 py-1 rounded-md text-[12px] font-medium transition-colors whitespace-nowrap", filter === item.id ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:text-foreground")}>{item.label}</button>
            ))}
          </div>
          <div className="relative sm:ml-auto sm:w-56">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label={t("orders.search")} placeholder={t("orders.search")} className="w-full h-9 pl-9 pr-3 rounded-lg bg-surface border border-border text-[13px] placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring/30" />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] table-fixed text-left">
            <colgroup><col style={{ width: "16%" }} /><col style={{ width: "30%" }} /><col style={{ width: "20%" }} /><col style={{ width: "18%" }} /><col style={{ width: "16%" }} /></colgroup>
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-medium px-5 py-3">{t("orders.col.order")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.customer")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("orders.col.total")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.status")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.date")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((order) => (
                <tr key={order.recordId} className="hover:bg-surface/50 transition-colors">
                  <td className="px-5 py-3 text-[13.5px] font-semibold tabular-nums">
                    <button type="button" onClick={() => setSelectedOrder(order)} className="text-primary hover:underline">#{order.id}</button>
                  </td>
                  <td className="px-5 py-3 text-[13.5px] font-medium">{order.customer}</td>
                  <td className="px-5 py-3 text-right text-[13.5px] font-semibold tabular-nums">{formatOrderMoney(order.total, order.currency)}</td>
                  <td className="px-5 py-3"><span className="rounded-md bg-surface px-2 py-1 text-xs">{t(`orders.status.${order.status}`, order.status)}</span></td>
                  <td className="px-5 py-3 text-[12.5px] text-muted-foreground">{order.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {orderState.loading && <div className="py-12 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        {!orderState.loading && orders.length > 0 && filtered.length === 0 && <div className="py-12 text-center text-[13.5px] text-muted-foreground">{t("orders.empty")}</div>}
        {!orderState.loading && orders.length === 0 && !orderState.error && <div className="py-12 text-center text-[13.5px] text-muted-foreground">{t("orders.empty")}</div>}
        {orderState.nextCursor && (
          <div className="border-t border-border p-3 text-center">
            <button type="button" onClick={orderState.loadMore} disabled={orderState.loadingMore} className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface disabled:opacity-60">
              {orderState.loadingMore && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("common.loadMore", "Load more")}
            </button>
          </div>
        )}
      </div>
      {selectedOrder && <OrderDetail order={selectedOrder} onClose={() => setSelectedOrder(null)} />}
    </div>
  );
}

function OrderDetail({ order, onClose }) {
  const t = useT();
  const [record, setRecord] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api(`/orders/${order.recordId}`)
      .then((data) => alive && setRecord(data))
      .catch((e) => alive && setError(e?.message || "Could not load order details."));
    return () => { alive = false; };
  }, [order.recordId]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <section role="dialog" aria-modal="true" aria-labelledby="order-detail-title" onClick={(event) => event.stopPropagation()} className="h-full w-full max-w-lg overflow-y-auto bg-card shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-border bg-card/90 px-5 py-4 backdrop-blur">
          <h2 id="order-detail-title" className="font-display text-base font-semibold">{t("orders.detail.title", "Order details")} #{order.id}</h2>
          <button type="button" aria-label={t("common.close", "Close")} onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg hover:bg-surface"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 p-5">
          {!record && !error && <p className="text-sm text-muted-foreground">{t("common.loading")}</p>}
          {error && <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
          {record && <>
            <div className="grid grid-cols-2 gap-3">
              <DetailField label={t("orders.col.status")} value={t(`orders.status.${record.status}`, record.status)} />
              <DetailField label={t("orders.col.total")} value={formatOrderMoney(record.grand_total, record.currency)} />
              <DetailField label={t("orders.kpi.aov")} value={record.net_collected == null ? "—" : formatOrderMoney(record.net_collected, record.currency)} />
              <DetailField label={t("orders.payment.refunded", "Refunded")} value={record.refunded_total == null ? "—" : formatOrderMoney(record.refunded_total, record.currency)} />
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">{t("orders.col.items")}</h3>
              <div className="space-y-2">
                {(record.items || []).length === 0 ? <p className="text-sm text-muted-foreground">—</p> : record.items.map((item) => (
                  <div key={item.id} className="rounded-lg border border-border p-3">
                    <div className="flex justify-between gap-3 text-sm">
                      <span className="font-medium">{item.title}</span>
                      <span>{item.quantity} × {formatOrderMoney(item.unit_price, record.currency)}</span>
                    </div>
                    {item.sku && <div className="mt-1 text-xs text-muted-foreground">{item.sku}</div>}
                  </div>
                ))}
              </div>
            </div>
          </>}
        </div>
      </section>
    </div>
  );
}

function DetailField({ label, value }) {
  return <div className="rounded-lg border border-border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 text-sm font-semibold">{value}</div></div>;
}
