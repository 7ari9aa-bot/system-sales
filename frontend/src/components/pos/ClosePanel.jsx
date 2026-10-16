import { useEffect, useState } from "react";
import { Loader2, Lock } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { money } from "./money";

/** قفل الوردية — «المتوقع قبل العدّ» لكل وسيلة، والمعدود قدامه.
 *
 * close-preview بييجي من الخادم (float + مدفوع − مرتجع لكل وسيلة)، والمعدود
 * بيتزرع مبدئياً بالمتوقع زي ما الكاشير يعدّ ويصحّح بيده. الفرق يظهر live. */
export default function ClosePanel({ sessionId, onClosed, onError }) {
  const t = useT();

  const [preview, setPreview] = useState(null);
  const [counted, setCounted] = useState({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await api(`/pos/sessions/${sessionId}/close-preview`);
        if (!alive) return;
        setPreview(data);
        const seeded = {};
        for (const row of data.by_method || []) seeded[row.method] = row.expected;
        setCounted(seeded);
      } catch (e) {
        onError?.(e?.message || t("pos.err.preview", "Could not load the close preview."));
      }
    })();
    return () => {
      alive = false;
    };
     
  }, [sessionId]);

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    try {
      const countedByMethod = {};
      for (const row of preview.by_method || []) {
        const value = String(counted[row.method] ?? row.expected).trim() || row.expected;
        countedByMethod[row.method] = value;
      }
      const closed = await api(`/pos/sessions/${sessionId}/close`, {
        method: "POST",
        body: {
          counted_cash: countedByMethod.cash ?? "0.00",
          counted_by_method: countedByMethod,
        },
      });
      onClosed(closed);
    } catch (e) {
      onError?.(e?.message || t("pos.err.close", "Could not close the drawer."));
    } finally {
      setBusy(false);
    }
  }

  if (!preview) {
    return (
      <div className="flex items-center gap-2 py-6 text-[13px] text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("pos.loadingPreview", "Loading the shift numbers…")}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-[12.5px] text-muted-foreground">
        {t("pos.closePreview", "Expected before counting")} ·{" "}
        {t("pos.invoices", "{n} sales", { n: preview.invoice_count })} ·{" "}
        {money(preview.sales_total)}
      </div>

      <div className="space-y-2">
        {preview.by_method.map((row) => {
          const variance = (
            Number(String(counted[row.method] ?? row.expected).replace(",", "")) -
            Number(row.expected)
          ).toFixed(2);
          return (
            <div key={row.method} className="flex items-center gap-2">
              <span className="text-[12.5px] flex-1">
                {t(`pos.method.${row.method}`)}
              </span>
              <span className="text-[12px] text-muted-foreground tabular-nums" dir="ltr">
                {money(row.expected)}
              </span>
              <input
                value={counted[row.method] ?? row.expected}
                onChange={(e) =>
                  setCounted((prev) => ({ ...prev, [row.method]: e.target.value }))
                }
                dir="ltr"
                inputMode="decimal"
                className="h-9 w-24 rounded-xl border border-border bg-surface px-2 text-[13px] tabular-nums"
              />
              <span
                className={
                  "w-16 text-end text-[12px] tabular-nums " +
                  (variance === "0.00"
                    ? "text-muted-foreground"
                    : "text-destructive")
                }
                dir="ltr"
              >
                {variance}
              </span>
            </div>
          );
        })}
      </div>

      <button
        type="button"
        onClick={confirm}
        disabled={busy}
        className="h-10 w-full rounded-xl border border-border text-[13px] font-medium disabled:opacity-50 inline-flex items-center justify-center gap-2"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
        {t("pos.confirmClose", "Close and reconcile")}
      </button>
    </div>
  );
}
