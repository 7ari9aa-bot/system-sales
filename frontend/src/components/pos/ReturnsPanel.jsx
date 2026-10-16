import { useEffect, useState } from "react";
import { Loader2, Plus, Repeat, Undo2 } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { dec, money } from "./money";

/** المرتجعات والاستبدال — شاشة واحدة بوضعين.
 *
 * المرتجع: اختار إيصال وكميات والخادم يسعّر بسعر الأصلي ويرد بطريقة الدفع
 * الأصلية. الاستبدال (نمط Shopify الحديث): نفس سطور المرتجع + بدائل من
 * الكتالوج، والفرق الصافي بسيتسدد أو يترجع — كله في ترانزاكشن واحدة.
 *
 * حساب الصافي في الواجهة مطابق لمعادلة الخادم سطر بسطر (نصيب الخصم
 * بالتناسب وتقريب HALF_UP للقرش) عشان الرقم على الشاشة هو الرقم المحسوب. */

function returnLineTotal(order, line, qty) {
  const gross = dec(line.unit_price) * qty;
  const subtotal = dec(order.subtotal ?? "0");
  const discount = dec(order.discount_total ?? "0");
  const share =
    subtotal > 0 && discount > 0
      ? Math.round((discount * gross * 100) / subtotal) / 100
      : 0;
  return Math.round((gross - share) * 100) / 100;
}

export default function ReturnsPanel({ sessionId, onDone, onNotice, onError }) {
  const t = useT();

  const [receipts, setReceipts] = useState([]);
  const [picked, setPicked] = useState(null);
  const [quantities, setQuantities] = useState({});
  const [restock, setRestock] = useState(true);
  const [busy, setBusy] = useState(false);

  // وضع الاستبدال
  const [mode, setMode] = useState("return"); // return | exchange
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [newLines, setNewLines] = useState([]);
  const [netMethod, setNetMethod] = useState("cash");

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
    setNewLines([]);
    setQ("");
    setResults([]);
    try {
      const detail = await api(`/pos/receipts/${receiptId}`);
      setPicked(detail);
    } catch (e) {
      onError?.(e?.message || t("pos.err.receipt", "Could not load that receipt."));
    }
  }

  function setQty(variantId, value) {
    const line = picked?.lines?.find((l) => l.variant_id === variantId) ?? null;
    // السقف: المبيع ناقص اللي رجع قبل كده — المرتجع التاني مبيقدرش يعدي.
    const max = line ? line.quantity - (line.returned_qty || 0) : 0;
    let n = Math.floor(Number(value));
    if (!Number.isFinite(n) || n < 0) n = 0;
    if (n > max) n = max;
    setQuantities((prev) => ({ ...prev, [variantId]: n }));
  }

  // ---------------------------------------------------------------- search -

  async function search(q) {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const page = await api(
        `/pos/sessions/${sessionId}/items?q=${encodeURIComponent(q)}&limit=8`
      );
      setResults(Array.isArray(page.items) ? page.items : []);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  function addReplacement(item) {
    setNewLines((prev) => {
      const i = prev.findIndex((l) => l.variant_id === item.variant_id);
      if (i >= 0) {
        const next = [...prev];
        next[i] = { ...next[i], quantity: next[i].quantity + 1 };
        return next;
      }
      return [
        ...prev,
        {
          variant_id: item.variant_id,
          title: item.title,
          sku: item.sku,
          unit_price: item.unit_price,
          quantity: 1,
        },
      ];
    });
  }

  function stepReplacement(variantId, delta) {
    setNewLines((prev) =>
      prev
        .map((l) => (l.variant_id === variantId ? { ...l, quantity: l.quantity + delta } : l))
        .filter((l) => l.quantity > 0)
    );
  }

  // ------------------------------------------------------------------ net --

  const returnTotal = picked
    ? (picked.lines || [])
        .reduce((acc, l) => acc + returnLineTotal(picked.order, l, quantities[l.variant_id] || 0), 0)
        .toFixed(2)
    : "0.00";
  const newTotal = newLines
    .reduce((acc, l) => acc + dec(l.unit_price) * l.quantity, 0)
    .toFixed(2);
  const net = (dec(newTotal) - dec(returnTotal)).toFixed(2); // موجب: على العميل

  async function submit() {
    if (!picked) return;
    const rlines = (picked.lines || [])
      .map((l) => ({ variant_id: l.variant_id, quantity: quantities[l.variant_id] || 0 }))
      .filter((l) => l.quantity > 0);
    if (rlines.length === 0) {
      onError?.(t("pos.err.noReturnLines", "Pick at least one unit to return."));
      return;
    }
    setBusy(true);
    try {
      if (mode === "exchange") {
        if (newLines.length === 0) {
          onError?.(t("pos.err.noReplacement", "Add the replacement items first."));
          return;
        }
        const body = {
          order_id: picked.order.id,
          return_lines: rlines,
          new_lines: newLines.map((l) => ({
            variant_id: l.variant_id,
            quantity: l.quantity,
          })),
          restock,
        };
        if (dec(net) > 0) {
          body.tenders = [{ method: netMethod, amount: net }];
        }
        const result = await api(`/pos/sessions/${sessionId}/exchanges`, {
          method: "POST",
          body,
        });
        onNotice?.(
          t("pos.exchanged", "Exchange done. Receipts {n} and {m}.", {
            n: result.return_receipt_number,
            m: result.new_receipt_number,
          })
        );
      } else {
        const result = await api(`/pos/sessions/${sessionId}/returns`, {
          method: "POST",
          body: { order_id: picked.order.id, lines: rlines, restock },
        });
        onNotice?.(
          t("pos.returned", "Return processed. Receipt {n} for {a}.", {
            n: result.receipt_number,
            a: money(result.refunded_total),
          })
        );
      }
      setPicked(null);
      setQuantities({});
      setNewLines([]);
      setMode("return");
      await loadReceipts();
      onDone?.();
    } catch (e) {
      onError?.(
        e?.message ||
          (mode === "exchange"
            ? t("pos.err.exchange", "Could not process the exchange.")
            : t("pos.err.returns", "Could not process the return."))
      );
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
                title={
                  r.returned_units > 0
                    ? t("pos.returnedBadge", "{n} returned", { n: r.returned_units })
                    : undefined
                }
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
          <div className="flex items-center justify-between">
            <div className="text-[12px] text-muted-foreground tabular-nums" dir="ltr">
              {picked.receipt.number} · {money(picked.order.grand_total)}
            </div>
            <div className="flex rounded-lg border border-border overflow-hidden text-[11.5px]">
              <button
                type="button"
                onClick={() => setMode("return")}
                className={
                  "px-2 py-1 inline-flex items-center gap-1 " +
                  (mode === "return" ? "bg-primary/10 text-primary" : "text-muted-foreground")
                }
              >
                <Undo2 className="h-3 w-3" />
                {t("pos.returnOnly", "Return only")}
              </button>
              <button
                type="button"
                onClick={() => setMode("exchange")}
                className={
                  "px-2 py-1 inline-flex items-center gap-1 border-s border-border " +
                  (mode === "exchange" ? "bg-primary/10 text-primary" : "text-muted-foreground")
                }
              >
                <Repeat className="h-3 w-3" />
                {t("pos.exchangeMode", "Exchange")}
              </button>
            </div>
          </div>

          {picked.order.fully_returned && mode === "return" ? (
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

              {mode === "exchange" && (
                <div className="rounded-lg border border-border p-2 space-y-2">
                  <div className="text-[12px] font-medium">
                    {t("pos.replacements", "Replacements")}
                  </div>
                  <div className="relative">
                    <input
                      value={q}
                      onChange={(e) => {
                        setQ(e.target.value);
                        void search(e.target.value);
                      }}
                      placeholder={t("pos.searchToAdd", "Scan or search the replacement…")}
                      dir="auto"
                      className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-[12.5px]"
                    />
                    {searching && (
                      <Loader2 className="absolute end-2 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
                    )}
                  </div>
                  {results.length > 0 && (
                    <ul className="space-y-1 max-h-32 overflow-y-auto">
                      {results.map((item) => (
                        <li key={item.variant_id}>
                          <button
                            type="button"
                            onClick={() => addReplacement(item)}
                            className="w-full flex items-center gap-2 rounded-lg border border-border px-2 py-1.5 text-[12px] hover:border-primary/40"
                          >
                            <Plus className="h-3 w-3 shrink-0" />
                            <span className="flex-1 truncate text-start" dir="auto">
                              {item.title || item.sku}
                            </span>
                            <span className="tabular-nums" dir="ltr">
                              {money(item.unit_price)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {newLines.length > 0 && (
                    <ul className="space-y-1">
                      {newLines.map((l) => (
                        <li key={l.variant_id} className="flex items-center gap-2 text-[12.5px]">
                          <span className="flex-1 truncate" dir="auto">
                            {l.title || l.sku}
                          </span>
                          <button type="button" aria-label="−" onClick={() => stepReplacement(l.variant_id, -1)} className="h-7 w-7 rounded-lg border border-border">−</button>
                          <span className="w-6 text-center tabular-nums">{l.quantity}</span>
                          <button type="button" aria-label="+" onClick={() => stepReplacement(l.variant_id, 1)} className="h-7 w-7 rounded-lg border border-border">+</button>
                          <span className="w-20 text-end tabular-nums" dir="ltr">
                            {money((dec(l.unit_price) * l.quantity).toFixed(2))}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <dl className="text-[12.5px] space-y-1 border-t border-border pt-2">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">{t("pos.returnEst", "Return value")}</dt>
                  <dd className="tabular-nums" dir="ltr">{money(returnTotal)}</dd>
                </div>
                {mode === "exchange" && (
                  <>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">{t("pos.newEst", "Replacements total")}</dt>
                      <dd className="tabular-nums" dir="ltr">{money(newTotal)}</dd>
                    </div>
                    {dec(net) > 0 ? (
                      <div className="flex justify-between font-medium">
                        <dt>{t("pos.netDue", "Customer owes")}</dt>
                        <dd className="tabular-nums" dir="ltr">{money(net)}</dd>
                      </div>
                    ) : dec(net) < 0 ? (
                      <div className="flex justify-between font-medium text-success">
                        <dt>{t("pos.netRefund", "Shop owes")}</dt>
                        <dd className="tabular-nums" dir="ltr">{money(net.replace("-", ""))}</dd>
                      </div>
                    ) : null}
                  </>
                )}
              </dl>

              {mode === "exchange" && dec(net) > 0 && (
                <div className="flex items-center gap-2">
                  <select
                    value={netMethod}
                    onChange={(e) => setNetMethod(e.target.value)}
                    className="h-9 flex-1 rounded-xl border border-border bg-surface px-2 text-[12.5px]"
                  >
                    {["cash", "card", "wallet", "bank_transfer"].map((m) => (
                      <option key={m} value={m}>
                        {t(`pos.method.${m}`)}
                      </option>
                    ))}
                  </select>
                  <span className="text-[12px] text-muted-foreground tabular-nums" dir="ltr">
                    {money(net)}
                  </span>
                </div>
              )}

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
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : mode === "exchange" ? (
                  <Repeat className="h-4 w-4" />
                ) : (
                  <Undo2 className="h-4 w-4" />
                )}
                {mode === "exchange"
                  ? t("pos.exchangeSubmit", "Process exchange")
                  : t("pos.returnAction", "Process return")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
