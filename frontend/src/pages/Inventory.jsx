import React, { useState, useEffect, useCallback, useMemo } from "react";
import { Plus, PackageX, Boxes, Minus, Loader2 } from "lucide-react";
import { api, apiCached, peekCache } from "@/lib/api";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";

const BALANCES_PATH = "/inventory/balances";

/** المخزون — أرصدة حقيقية من GET /inventory/balances: كل صف رصيد
 *  (variant × warehouse) بـon_hand وreserved. التعديل مش PATCH —
 *  حركة مخزون محاسبية عبر POST /inventory/movements (direction
 *  in/out + quantity + reason من المفردات المغلقة M9)، والرصيد
 *  الجديد بيرجع من الخادم نفسه (balance_after). الحالة مش تقدير
 *  عميل: نفد فقط لما on_hand يكون صفر فعلاً. */
export default function Inventory() {
  const t = useT();
  const [items, setItems] = useState(() => peekCache(BALANCES_PATH));
  const [adjusting, setAdjusting] = useState(null);
  const [error, setError] = useState(null);
  const [metadataError, setMetadataError] = useState("");
  const [metadata, setMetadata] = useState({ products: [], warehouses: [] });
  const [loading, setLoading] = useState(() => peekCache(BALANCES_PATH) == null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [balancesResult, productsResult, warehousesResult] = await Promise.allSettled([
        apiCached(BALANCES_PATH),
        apiCached("/products?limit=200&offset=0"),
        apiCached("/warehouses?limit=200&offset=0"),
      ]);
      if (balancesResult.status === "rejected") throw balancesResult.reason;
      if (!Array.isArray(balancesResult.value)) throw new Error("The server returned invalid inventory balances.");
      const list = balancesResult.value;
      const productRows = productsResult.status === "fulfilled" && Array.isArray(productsResult.value)
        ? productsResult.value
        : [];
      const warehouseRows = warehousesResult.status === "fulfilled" && Array.isArray(warehousesResult.value)
        ? warehousesResult.value
        : [];
      const metadataWarnings = [];
      if (productsResult.status === "rejected" || !Array.isArray(productsResult.value)) {
        metadataWarnings.push(t("inventory.productNamesUnavailable", "Product names could not be loaded."));
      }
      if (warehousesResult.status === "rejected" || !Array.isArray(warehousesResult.value)) {
        metadataWarnings.push(t("inventory.warehouseNamesUnavailable", "Warehouse names could not be loaded."));
      }
      setItems(Array.isArray(list) ? list : []);
      const variantNames = new Map();
      for (const product of productRows) {
        for (const variant of product.variants || []) {
          variantNames.set(variant.id, {
            product: product.title,
            variant: variant.title || variant.sku || "",
          });
        }
      }
      setMetadata({
        variantNames,
        warehouses: new Map(warehouseRows.map((row) => [row.id, row.name])),
      });
      setMetadataError(metadataWarnings.join(" "));
      setError(null);
    } catch (e) {
      setError(e?.message || "Could not load inventory balances.");
      setItems((prev) => (Array.isArray(prev) ? prev : null));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const list = items || [];
  const out = list.filter((b) => (Number(b.on_hand) || 0) - (Number(b.reserved) || 0) <= 0).length;
  const totalReserved = list.reduce((s, b) => s + (Number(b.reserved) || 0), 0);
  const totalOnHand = list.reduce((s, b) => s + (Number(b.on_hand) || 0), 0);

  async function adjust(b, delta) {
    setAdjusting(`${b.variant_id}-${b.warehouse_id}`);
    setError(null);
    try {
      await api("/inventory/movements", {
        method: "POST",
        body: {
          variant_id: b.variant_id,
          warehouse_id: b.warehouse_id,
          direction: delta > 0 ? "in" : "out",
          quantity: Math.abs(delta),
          reason: "adjustment",
        },
      });
      await load();
    } catch (e) {
      setError(e?.message || "—");
    } finally {
      setAdjusting(null);
    }
  }

  const metadataMaps = useMemo(() => ({
    variantNames: metadata.variantNames || new Map(),
    warehouses: metadata.warehouses || new Map(),
  }), [metadata]);

  return (
    <div>
      <PageHeader title={t("inventory.title")} subtitle={t("inventory.subtitle")} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-5">
        <Stat icon={<Boxes className="h-5 w-5" />} tone="primary" value={list.length} label={t("inventory.balances")} />
        <Stat icon={<Boxes className="h-5 w-5" />} tone="success" value={totalOnHand} label={t("inventory.onHandTotal")} />
        <Stat icon={<Boxes className="h-5 w-5" />} tone="warning" value={totalReserved} label={t("inventory.reservedTotal")} />
        <Stat icon={<PackageX className="h-5 w-5" />} tone="destructive" value={out} label={t("inventory.outOfStock")} />
      </div>

      {error && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          <span>{error}</span>
          {items === null && <button type="button" onClick={() => void load()} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>}
        </div>
      )}

      {metadataError && (
        <div role="status" className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2.5 text-[12px] text-muted-foreground">
          <span>{metadataError} {t("inventory.namesFallbackHint", "IDs may appear instead of names.")}</span>
          <button type="button" onClick={() => void load()} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
        </div>
      )}

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {loading && items === null ? (
          <div className="py-16 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
        ) : error && items === null ? (
          <div className="py-12 text-center text-[13.5px] text-destructive">{error}</div>
        ) : list.length === 0 ? (
          <div className="py-12 text-center text-[13.5px] text-muted-foreground">{t("products.empty")}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] table-fixed text-left">
              <colgroup>
                <col style={{ width: "26%" }} /><col style={{ width: "26%" }} /><col style={{ width: "14%" }} />
                <col style={{ width: "14%" }} /><col style={{ width: "10%" }} /><col style={{ width: "10%" }} />
              </colgroup>
              <thead>
                <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                  <th className="font-medium px-5 py-3">{t("inventory.col.variant")}</th>
                  <th className="font-medium px-5 py-3">{t("inventory.col.warehouse")}</th>
                  <th className="font-medium px-5 py-3 text-center">{t("inventory.onHand")}</th>
                  <th className="font-medium px-5 py-3 text-center">{t("inventory.reserved")}</th>
                  <th className="font-medium px-5 py-3">{t("inventory.col.status")}</th>
                  <th className="font-medium px-5 py-3 text-center">{t("inventory.adjust")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {list.map((b) => {
                  const onHand = Number(b.on_hand) || 0;
                  const available = onHand - (Number(b.reserved) || 0);
                  const outNow = available <= 0;
                  const rowKey = `${b.variant_id}-${b.warehouse_id}`;
                  const names = metadataMaps.variantNames.get(b.variant_id);
                  const variantLabel = names ? [names.product, names.variant].filter(Boolean).join(" · ") : `${b.variant_id?.slice(0, 8)}…`;
                  const warehouseLabel = metadataMaps.warehouses.get(b.warehouse_id) || `${b.warehouse_id?.slice(0, 8)}…`;
                  return (
                    <tr key={rowKey} className="hover:bg-surface/50 transition-colors">
                      <td className="px-5 py-3 text-[12.5px] font-medium" dir="auto">{variantLabel}</td>
                      <td className="px-5 py-3 text-[12.5px] text-muted-foreground" dir="auto">{warehouseLabel}</td>
                      <td className="px-5 py-3 text-center text-[13.5px] font-semibold tabular-nums" dir="ltr">{onHand}</td>
                      <td className="px-5 py-3 text-center text-[13.5px] tabular-nums text-muted-foreground" dir="ltr">{Number(b.reserved) || 0}</td>
                      <td className="px-5 py-3">
                        {outNow ? (
                          <Badge tone="destructive">{t("inventory.out")}</Badge>
                        ) : (
                          <Badge tone="success">{t("inventory.in")}</Badge>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center justify-center gap-1.5">
                          <button type="button" aria-label={t("inventory.decrease", "Decrease stock")} onClick={() => adjust(b, -1)} disabled={adjusting === rowKey || outNow} className="h-8 w-8 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Minus className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label={t("inventory.increase", "Increase stock")} onClick={() => adjust(b, 1)} disabled={adjusting === rowKey} className="h-8 w-8 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Plus className="h-3.5 w-3.5" /></button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
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
