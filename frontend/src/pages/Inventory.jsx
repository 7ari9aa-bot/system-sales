import React, { useState, useEffect, useCallback } from "react";
import { Plus, AlertTriangle, PackageX, Boxes, Minus, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader, Badge, Delta } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";

function deriveStatus(stock) {
  const n = Number(stock) || 0;
  if (n <= 0) return "out";
  if (n < 20) return "low";
  return "in-stock";
}

export default function Inventory() {
  const t = useT();
  const [items, setItems] = useState(null);
  const [adjusting, setAdjusting] = useState(null);

  const load = useCallback(async () => {
    try {
      const list = await api('/inventory/balances');
      setItems(list);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const STATUS = {
    "in-stock": { label: t("inventory.status.inStock"), tone: "success" },
    low: { label: t("inventory.status.low"), tone: "warning" },
    out: { label: t("inventory.status.out"), tone: "destructive" },
  };

  const list = items || [];
  const inStock = list.filter((p) => p.status === "in-stock").length;
  const low = list.filter((p) => p.status === "low").length;
  const out = list.filter((p) => p.status === "out").length;
  const value = list.reduce((s, p) => s + (p.price || 0) * (p.stock || 0), 0);

  async function adjust(p, delta) {
    setAdjusting(p.id);
    const newStock = Math.max(0, (p.stock || 0) + delta);
    await api(`/inventory/balances/${p.id}`, { method: 'PATCH', body: { on_hand: newStock } });
    setAdjusting(null);
    load();
  }

  return (
    <div>
      <PageHeader title={t("inventory.title")} subtitle={t("inventory.subtitle")} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-5">
        <Stat icon={<Boxes className="h-5 w-5" />} tone="success" value={inStock} label={t("inventory.inStock")} />
        <Stat icon={<AlertTriangle className="h-5 w-5" />} tone="warning" value={low} label={t("inventory.runningLow")} />
        <Stat icon={<PackageX className="h-5 w-5" />} tone="destructive" value={out} label={t("inventory.outOfStock")} />
        <Stat icon={<Boxes className="h-5 w-5" />} tone="primary" value={formatCurrency(value, true)} label={t("inventory.value")} />
      </div>

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {items === null ? (
          <div className="py-16 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : list.length === 0 ? (
          <div className="py-12 text-center text-[13.5px] text-muted-foreground">{t("products.empty")}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] table-fixed text-left">
              <colgroup>
                <col style={{ width: "24%" }} /><col style={{ width: "14%" }} /><col style={{ width: "13%" }} /><col style={{ width: "10%" }} />
                <col style={{ width: "14%" }} /><col style={{ width: "12%" }} /><col style={{ width: "13%" }} />
              </colgroup>
              <thead>
                <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                  <th className="font-medium px-5 py-3">{t("inventory.col.product")}</th>
                  <th className="font-medium px-5 py-3">{t("inventory.col.sku")}</th>
                  <th className="font-medium px-5 py-3 text-right">{t("inventory.col.price")}</th>
                  <th className="font-medium px-5 py-3 text-center">{t("inventory.col.stock")}</th>
                  <th className="font-medium px-5 py-3">{t("inventory.col.status")}</th>
                  <th className="font-medium px-5 py-3 text-right">{t("inventory.col.trend")}</th>
                  <th className="font-medium px-5 py-3 text-center">{t("inventory.adjust")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {list.map((p) => (
                  <tr key={p.id} className="hover:bg-surface/50 transition-colors">
                    <td className="px-5 py-3 text-[13.5px] font-medium">{p.name}</td>
                    <td className="px-5 py-3 text-[12.5px] text-muted-foreground tabular-nums">{p.sku || "—"}</td>
                    <td className="px-5 py-3 text-right text-[13.5px] tabular-nums">{formatCurrency(p.price)}</td>
                    <td className="px-5 py-3 text-center text-[13.5px] font-semibold tabular-nums">{p.stock}</td>
                    <td className="px-5 py-3"><Badge tone={STATUS[p.status]?.tone}>{STATUS[p.status]?.label}</Badge></td>
                    <td className="px-5 py-3 text-right">{p.trend !== 0 && p.trend != null && <Delta value={p.trend} className="text-[11px]" />}</td>
                    <td className="px-5 py-3">
                      <div className="flex items-center justify-center gap-1.5">
                        <button onClick={() => adjust(p, -1)} disabled={adjusting === p.id} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Minus className="h-3.5 w-3.5" /></button>
                        <button onClick={() => adjust(p, 1)} disabled={adjusting === p.id} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Plus className="h-3.5 w-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ icon, tone, value, label }) {
  const toneClass = {
    success: "bg-success/15 text-success",
    warning: "bg-warning/15 text-warning",
    destructive: "bg-destructive/15 text-destructive",
    primary: "bg-primary/10 text-primary",
  }[tone];
  return (
    <div className="rounded-2xl bg-card border border-border p-5 flex items-center gap-3.5">
      <span className={`h-11 w-11 rounded-xl grid place-items-center ${toneClass}`}>{icon}</span>
      <div className="min-w-0">
        <div className="font-display text-[22px] font-semibold tabular-nums leading-none whitespace-nowrap">{value}</div>
        <div className="text-[12.5px] text-muted-foreground mt-1 whitespace-nowrap truncate">{label}</div>
      </div>
    </div>
  );
}