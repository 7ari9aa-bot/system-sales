import React, { useState, useEffect, useCallback } from "react";
import { Plus, AlertTriangle, PackageX, Boxes, Minus, Loader2 } from "lucide-react";
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

  const load = useCallback(async () => {
    try {
      const list = await apiCached(BALANCES_PATH);
      setItems(Array.isArray(list) ? list : []);
      setError(null);
    } catch {
      setItems((prev) => (Array.isArray(prev) ? prev : []));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const list = items || [];
  const out = list.filter((b) => Number(b.on_hand) <= 0).length;
  const totalReserved = list.reduce((s, b) => s + (Number(b.reserved) || 0), 0);
  const totalOnHand = list.reduce((s, b) => s + (Number(b.on_hand) || 0), 0);

  async function adjust(b, delta) {
    setAdjusting(b.variant_id);
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
      setAdjusting(null);
    }
  }

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
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          {t("inventory.adjustError")}: {error}
        </div>
      )}

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        {items === null ? (
          <div className="py-16 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
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
                  const outNow = onHand <= 0;
                  return (
                    <tr key={`${b.variant_id}-${b.warehouse_id}`} className="hover:bg-surface/50 transition-colors">
                      <td className="px-5 py-3 text-[12.5px] font-medium tabular-nums" dir="ltr">{b.variant_id?.slice(0, 8)}…</td>
                      <td className="px-5 py-3 text-[12.5px] text-muted-foreground tabular-nums" dir="ltr">{b.warehouse_id?.slice(0, 8)}…</td>
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
                          <button onClick={() => adjust(b, -1)} disabled={adjusting === b.variant_id} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Minus className="h-3.5 w-3.5" /></button>
                          <button onClick={() => adjust(b, 1)} disabled={adjusting === b.variant_id} className="h-7 w-7 grid place-items-center rounded-lg border border-border hover:bg-surface disabled:opacity-50"><Plus className="h-3.5 w-3.5" /></button>
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
