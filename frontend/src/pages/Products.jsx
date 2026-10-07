import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Search, Plus, Package, Pencil, Trash2, Loader2 } from "lucide-react";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/dashboardData";
import { api, apiCached } from "@/lib/api";
import ProductDialog from "@/components/products/ProductDialog";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function stockStatus(stock, threshold) {
  if (stock == null) return "unknown";
  if (stock <= 0) return "out";
  if (threshold == null) return "unknown";
  if (stock <= threshold) return "low";
  return "in-stock";
}

function ProductImage({ product }) {
  const images = Array.isArray(product.images) ? product.images : [];
  const imageUrl = images.length ? images[images.length - 1]?.url : "";
  const [failed, setFailed] = useState(false);
  if (!imageUrl || failed) return <Package className="h-10 w-10 text-muted-foreground/40" />;
  return <img src={imageUrl} alt={images[images.length - 1]?.alt || product.name || ""} onError={() => setFailed(true)} className="absolute inset-0 h-full w-full object-cover" />;
}

function toProduct(product, balances, threshold) {
  const variants = Array.isArray(product.variants) ? product.variants : [];
  const primaryVariant = variants.find((variant) => variant.is_active) || variants[0] || null;
  const stock = balances == null || variants.length === 0
    ? null
    : variants.reduce((total, variant) => total + balances
      .filter((balance) => balance.variant_id === variant.id)
      .reduce((sum, balance) => sum + Math.max(0, (Number(balance.on_hand) || 0) - (Number(balance.reserved) || 0)), 0), 0);
  return {
    ...product,
    name: product.title,
    variants,
    variant_id: primaryVariant?.id || null,
    sku: primaryVariant?.sku || "",
    price: primaryVariant?.price ?? null,
    stock,
    status: stockStatus(stock, threshold),
  };
}

export default function Products() {
  const t = useT();
  const [items, setItems] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [products, balances, dashboard] = await Promise.all([
        api("/products?limit=100&offset=0"),
        api("/inventory/balances?limit=200").catch(() => null),
        apiCached("/analytics/dashboard").catch(() => null),
      ]);
      if (!Array.isArray(products)) throw new Error("The server returned an invalid product list.");
      const stockRows = Array.isArray(balances) ? balances : null;
      const threshold = dashboard?.low_stock_threshold != null && Number.isFinite(Number(dashboard.low_stock_threshold))
        ? Number(dashboard.low_stock_threshold)
        : null;
      setItems(products.map((product) => toProduct(product, stockRows, threshold)));
      setError(stockRows === null
        ? t("products.stockLoadWarning", "Products loaded, but inventory balances are unavailable.")
        : threshold === null
          ? t("products.stockThresholdUnavailable", "Products loaded, but the workspace low-stock threshold is unavailable.")
          : null);
    } catch (e) {
      setError(e?.message || "Could not load products.");
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const statusLabels = {
    "in-stock": { label: t("products.status.inStock"), tone: "success" },
    low: { label: t("products.status.low"), tone: "warning" },
    out: { label: t("products.status.out"), tone: "destructive" },
    unknown: { label: t("products.stockUnknown", "Stock unavailable"), tone: "muted" },
  };
  const filters = [
    { id: "all", label: t("products.filter.all") },
    { id: "in-stock", label: t("products.status.inStock") },
    { id: "low", label: t("products.status.low") },
    { id: "out", label: t("products.status.out") },
  ];

  const filtered = useMemo(() => (items || []).filter((product) => {
    const needle = query.trim().toLowerCase();
    const matchesQuery = !needle || [product.name, product.sku, product.slug]
      .some((value) => String(value || "").toLowerCase().includes(needle));
    return matchesQuery && (filter === "all" || product.status === filter);
  }), [items, query, filter]);

  async function archive(product) {
    if (!window.confirm(t("products.deleteConfirm"))) return;
    setError(null);
    try {
      await api(`/products/${product.id}/archive`, { method: "POST" });
      await load();
    } catch (e) {
      setError(e?.message || t("products.archive.error", "Could not archive this product."));
    }
  }

  return (
    <div>
      <PageHeader
        title={t("products.title")}
        subtitle={t("products.subtitle")}
        actions={<button type="button" onClick={() => { setEditing(null); setDialogOpen(true); }} className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
          <Plus className="h-4 w-4" /> {t("products.add")}
        </button>}
      />

      {error && <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <span>{error}</span>
        {items === null && <button type="button" onClick={() => void load()} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>}
      </div>}

      <div className="flex flex-col sm:flex-row gap-2.5 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} aria-label={t("products.search")} placeholder={t("products.search")} className="w-full h-9 pl-9 pr-3 rounded-lg bg-card border border-border text-[13px] placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring/30" />
        </div>
        <div className="flex gap-1">
          {filters.map((item) => (
            <button key={item.id} type="button" aria-pressed={filter === item.id} onClick={() => setFilter(item.id)} className={cn("px-2.5 py-1.5 rounded-md text-[12px] font-medium", filter === item.id ? "bg-primary text-primary-foreground" : "bg-card border border-border text-muted-foreground hover:text-foreground")}>{item.label}</button>
          ))}
        </div>
      </div>

      {loading && items === null ? (
        <div className="py-16 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : error && items === null ? (
        <div className="py-12 text-center text-[13.5px] text-destructive">{error}</div>
      ) : error && items?.length === 0 ? (
        <div className="py-12 text-center text-[13.5px] text-destructive">{error}</div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <Package className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-[13.5px] text-muted-foreground">{items?.length === 0 ? t("products.empty") : t("products.noResults")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((product) => {
            const status = statusLabels[product.status] || statusLabels.unknown;
            return (
              <div key={product.id} className="rounded-2xl bg-card border border-border overflow-hidden hover:shadow-sm transition-shadow group">
                <div className="aspect-[4/3] bg-surface grid place-items-center overflow-hidden relative">
                  <ProductImage product={product} />
                  <div className="absolute top-2 right-2 flex gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 transition-opacity">
                    <button type="button" aria-label={`${t("products.edit")} ${product.name}`} onClick={() => { setEditing(product); setDialogOpen(true); }} className="h-8 w-8 grid place-items-center rounded-lg bg-card/90 border border-border hover:bg-surface"><Pencil className="h-3.5 w-3.5" /></button>
                    <button type="button" aria-label={`${t("products.archive", "Archive")} ${product.name}`} onClick={() => archive(product)} className="h-8 w-8 grid place-items-center rounded-lg bg-card/90 border border-border hover:bg-destructive/10 hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[13.5px] font-medium truncate">{product.name || "—"}</div>
                      <div className="text-[11.5px] text-muted-foreground">{product.sku || "—"}</div>
                    </div>
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </div>
                  <div className="mt-3 flex items-end justify-between">
                    <div>
                      <div className="font-display text-[18px] font-semibold tabular-nums">{product.price == null ? "—" : formatCurrency(Number(product.price))}</div>
                      <div className="text-[11.5px] text-muted-foreground">{product.stock == null ? "—" : `${product.stock} ${t("products.unitsLeft")}`}</div>
                    </div>
                    <span className="text-[11px] text-muted-foreground">{product.variants.length} {t("products.variants", "variants")}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ProductDialog open={dialogOpen} product={editing} onClose={() => setDialogOpen(false)} onSaved={load} />
    </div>
  );
}
