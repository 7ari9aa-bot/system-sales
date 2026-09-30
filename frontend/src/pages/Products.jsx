import React, { useState, useEffect, useCallback } from "react";
import { Plus, Search, Package, Pencil, Trash2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader, Badge, Delta } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";
import ProductDialog from "@/components/products/ProductDialog";
import { cn } from "@/lib/utils";

export default function Products() {
  const t = useT();
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const list = await api('/products');
      setItems(list);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const STATUS = {
    "in-stock": { label: t("products.status.inStock"), tone: "success" },
    low: { label: t("products.status.low"), tone: "warning" },
    out: { label: t("products.status.out"), tone: "destructive" },
  };
  const FILTERS = [
    { id: "all", label: t("products.filter.all") },
    { id: "in-stock", label: t("products.status.inStock") },
    { id: "low", label: t("products.status.low") },
    { id: "out", label: t("products.status.out") },
  ];

  const filtered = (items || []).filter((p) => {
    const matchQ = !q || p.name?.toLowerCase().includes(q.toLowerCase()) || p.sku?.toLowerCase().includes(q.toLowerCase());
    const matchF = filter === "all" || p.status === filter;
    return matchQ && matchF;
  });

  async function remove(p) {
    if (!window.confirm(t("products.deleteConfirm"))) return;
    await api(`/products/${p.id}`, { method: 'DELETE' });
    load();
  }

  return (
    <div>
      <PageHeader
        title={t("products.title")}
        subtitle={t("products.subtitle")}
        actions={
          <button onClick={() => { setEditing(null); setDialogOpen(true); }} className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
            <Plus className="h-4 w-4" /> {t("products.add")}
          </button>
        }
      />

      <div className="flex flex-col sm:flex-row gap-2.5 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("products.search")} className="w-full h-9 pl-9 pr-3 rounded-lg bg-card border border-border text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/30" />
        </div>
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button key={f.id} onClick={() => setFilter(f.id)} className={cn("px-2.5 py-1.5 rounded-md text-[12px] font-medium", filter === f.id ? "bg-primary text-primary-foreground" : "bg-card border border-border text-muted-foreground hover:text-foreground")}>{f.label}</button>
          ))}
        </div>
      </div>

      {items === null ? (
        <div className="py-16 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center">
          <Package className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-[13.5px] text-muted-foreground">{items.length === 0 ? t("products.empty") : t("products.noResults")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((p) => (
            <div key={p.id} className="rounded-2xl bg-card border border-border overflow-hidden hover:shadow-sm transition-shadow group">
              <div className="aspect-[4/3] bg-surface grid place-items-center overflow-hidden relative">
                {p.image_url ? (
                  <img src={p.image_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <Package className="h-10 w-10 text-muted-foreground/40" />
                )}
                <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => { setEditing(p); setDialogOpen(true); }} className="h-7 w-7 grid place-items-center rounded-lg bg-card/90 border border-border hover:bg-surface"><Pencil className="h-3.5 w-3.5" /></button>
                  <button onClick={() => remove(p)} className="h-7 w-7 grid place-items-center rounded-lg bg-card/90 border border-border hover:bg-destructive/10 hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>
              <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-medium truncate">{p.name}</div>
                    <div className="text-[11.5px] text-muted-foreground">{p.sku || "—"}</div>
                  </div>
                  <Badge tone={STATUS[p.status]?.tone || "muted"}>{STATUS[p.status]?.label || p.status}</Badge>
                </div>
                <div className="mt-3 flex items-end justify-between">
                  <div>
                    <div className="font-display text-[18px] font-semibold tabular-nums">{formatCurrency(p.price)}</div>
                    <div className="text-[11.5px] text-muted-foreground">{p.stock} {t("products.unitsLeft")}</div>
                  </div>
                  {p.trend !== 0 && p.trend != null && <Delta value={p.trend} className="text-[11px]" />}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <ProductDialog open={dialogOpen} product={editing} onClose={() => setDialogOpen(false)} onSaved={load} />
    </div>
  );
}