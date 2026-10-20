/**
 * Replacement lines of an exchange. Pure helpers (tested) + one hook.
 * Price shown per line is the catalog price (a preview); the TOTAL and the difference always come
 * from the backend quote: the backend prices a replacement off the CURRENT price with NO discount.
 * Stock is limited on the screen too, because /quote does not check stock (only the exchange does).
 */
import { useEffect, useMemo, useState } from "react";
import { latestOnly } from "./latest";
import { posApi } from "./posApi";

export const replacementLine = (v) => ({
  lineId: String(v.id),
  variantId: v.id,
  code: v.sku,
  barcode: v.barcode,
  name: v.productName,
  color: v.color,
  hex: undefined,
  size: v.size,
  stock: v.stock,
  price: v.sellPrice,
  qty: 1,
});

/** Add one unit; refuses past the available stock and says why. */
export function addReplacement(lines, variant) {
  if (!variant || variant.stock <= 0) return { lines, ok: false, reason: "نافد من المخزون" };
  const existing = lines.find((l) => l.variantId === variant.id);
  if (!existing) return { lines: [...lines, replacementLine(variant)], ok: true };
  if (existing.qty >= variant.stock) return { lines, ok: false, reason: `المتاح ${variant.stock} فقط` };
  return { lines: lines.map((l) => (l.variantId === variant.id ? { ...l, qty: l.qty + 1 } : l)), ok: true };
}

export const clampReplacementQty = (line, value) => Math.max(1, Math.min(Math.max(line.stock, 1), Math.trunc(Number(value)) || 1));

export const setReplacementQty = (lines, lineId, value) => lines.map((l) => (l.lineId === lineId ? { ...l, qty: clampReplacementQty(l, value) } : l));

export const removeReplacement = (lines, lineId) => lines.filter((l) => l.lineId !== lineId);

/** Preview total in cents (catalog prices). Only shown until the backend quote arrives. */
export const previewTotal = (lines) => lines.reduce((s, l) => s + Math.round(l.price * 100) * l.qty, 0) / 100;

const EMPTY = { total: "0.00", loading: false, error: null };

/** The backend price of the replacement lines; a newer request always wins over a slower older one. */
export function useExchangeQuote(sessionId, lines) {
  const [quote, setQuote] = useState(EMPTY);
  const run = useMemo(
    () =>
      latestOnly(
        (r) => setQuote({ total: r.grand_total, loading: false, error: null }),
        (e) => setQuote((q) => ({ ...q, loading: false, error: e?.message || "تعذّر حساب إجمالي البدائل" })),
      ),
    [],
  );
  const key = JSON.stringify(lines.map((l) => [l.variantId, l.qty]));
  useEffect(() => {
    if (!sessionId || lines.length === 0) {
      run.cancel();
      setQuote(EMPTY);
      return;
    }
    setQuote((q) => ({ ...q, loading: true, error: null }));
    run(() => posApi.quote(sessionId, { items: lines.map((l) => ({ variant_id: l.variantId, quantity: l.qty })) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, key, run]);
  return quote;
}
