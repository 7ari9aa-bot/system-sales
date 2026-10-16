import { useEffect, useState } from "react";
import { Loader2, Undo2 } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { money } from "./money";

/** المرتجعات — اختار إيصال بيع من الوردية، حدّد كميات السطور، ونفّذ.
 *
 * الخادم هو اللي بيسعّر المرتجع بسعر البيعة الأصلي وبيوزّع الرفع على وسايل
 * الدفع الأصلية — الواجهة بتحدد «إيه راجع» بس. */
export default function ReturnsPanel({ sessionId, onDone, onError }) {
  const t = useT();

  const [receipts, setReceipts] = useState([]);
  const [picked, setPicked] = useState(null);
  const [quantities, setQuantities] = useState({});
  const [restock, setRestock] = useState(true);
  const [busy, setBusy] = useState(false);

  async function loadReceipts() {
    try {
      const rows = await api(`/pos/sessions/${sessionId}/receipts`);
      setReceipts((Array.isArray(rows) ? rows : []).filter((r) => r.kind === "sale"));
    } catch {
      setReceipts([]);
    }
  }

  useEffect(() => {
    void loadReceipts();
     
  }, [sessionId]);

  async function pick(receiptId) {
    setPicked(null);
    setQuantities({});
    try {
      const detail = await api(`/pos/receipts/${receiptId}`);
      setPicked(detail);
    } catch (e) {
      onError?.(e?.message || t("pos.err.receipt", "Could not load that receipt."));
    }
  }

  function setQty(variantId, value) {
    const line =
      picked?.lines?.find((l) => l.variant_id === variantId) ?? null;
    // السقف: المبيع ناقص اللي رجع قبل كده — المرتجع التاني مبيقدرش يعدي.
    const max = line ? line.quantity - (line.returned_qty || 0) : 0;
    let n = Math.floor(Number(value));
    if (!Number.isFinite(n) || n < 0) n = 0;
    if (n > max) n = max;
    setQuantities((prev) => ({ ...prev, [variantId]: n }));
  }

  async function submit() {
    if (!picked) return;
    const lines = (picked.lines || [])
      .map((l) => ({ variant_id: l.variant_id, quantity: quantities[l.variant_id] || 0 }))
      .filter((l) => l.quantity > 0);
    if (lines.length === 0) {
      onError?.(t("pos.err.noReturnLines", "Pick at least one unit to return."));
      return;
    }
    setBusy(true);
    try {
      const result = await api(`/pos/sessions/${sessionId}/returns`, {
        method: "POST",
        body: { order_id: picked.order.id, lines, restock },
      });
      onNotice(
        t("pos.returned", "Return processed. Receipt {n} for {a}.", {
          n: result.receipt_number,
          a: money(result.refunded_total),
        })
      );
      setPicked(null);
      setQuantities({});
      await loadReceipts();
      onDone?.(result);
    } catch (e) {
      onError?.(e?.message || t("pos.err.returns", "Could not process the return."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="text-[12.5px] font-medium mb-1.5">
          {t("pos.pickReceipt", "Pick a receipt to return")}
        </div>
        {receipts.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">
            {t("pos.noReceipts", "No receipts on this shift yet.")}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
            {receipts.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => pick(r.id)}
                title={r.returned_units > 0 ? t("pos.returnedBadge", "{n} returned", { n: r.returned_units }) : undefined}
                dir="ltr"
                className={
                  "rounded-xl border px-2.5 py-1.5 text-[11.5px] tabular-nums hover:border-primary/40 " +
                  (r.returned_units > 0
                    ? "border-warning/40 bg-warning/5 text-warning"
                    : "border-border bg-surface")
                }
              >
                {r.number}
                {r.returned_units > 0 ? ` ↩${r.returned_units}` : ""}
              </button>
            ))}
          </div>
        )}
      </div>

      {picked && (
        <div className="rounded-xl border border-border p-3 space-y-2">
          <div className="text-[12px] text-muted-foreground tabular-nums" dir="ltr">
            {picked.receipt.number} · {money(picked.order.grand_total)}
          </div>
          {picked.order.fully_returned ? (
            <p className="text-[12.5px] text-warning">
              {t("pos.fullyReturned", "This sale was fully returned already.")}
            </p>
          ) : (
            <>
              <ul className="space-y-1.5">
                {(picked.lines || []).map((l) => (
                  <li key={l.variant_id} className="flex items-center gap-2 text-[12.5px]">
                    <span className="flex-1 truncate" dir="auto">
                      {l.title || l.sku || l.variant_id.slice(0, 8)}
                    </span>
                    <span className="text-[11px] text-muted-foreground" dir="ltr">
                      ×{l.quantity}
                      {l.returned_qty > 0 ? ` (↩${l.returned_qty})` : ""}
                    </span>
                    <input
                      value={quantities[l.variant_id] ?? 0}
                      onChange={(e) => setQty(l.variant_id, e.target.value)}
                      dir="ltr"
                      inputMode="numeric"
                      className="h-8 w-16 rounded-lg border border-border bg-surface px-2 text-[12.5px] tabular-nums"
                    />
                  </li>
                ))}
              </ul>
              <label className="inline-flex items-center gap-2 text-[12.5px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={restock}
                  onChange={(e) => setRestock(e.target.checked)}
                />
                {t("pos.restock", "Put the goods back on the shelf")}
              </label>
              <button
                type="button"
                onClick={submit}
                disabled={busy}
                className="h-9 w-full rounded-xl border border-border text-[12.5px] font-medium disabled:opacity-50 inline-flex items-center justify-center gap-2"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />}
                {t("pos.returnAction", "Process return")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
