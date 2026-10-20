import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { buildCatalog, searchCatalog } from "./catalogAdapter";
import { clampQty } from "./checkout";
import { createSaleSession } from "./saleSession";
import { receiptFromApi } from "./receiptAdapter";
import { heldFromApi, holdPayload, restoreHeld } from "./heldCarts";
import { fromMinor } from "./money";
import { discountMinor, latestOnly } from "./latest";

export const CATALOG_KEY = ["cashier", "catalog"];
export const HELD_KEY = (sessionId) => ["cashier", "held", sessionId];

/** Carts parked on this shift, oldest first. */
export function useHeldCarts(sessionId, catalog) {
  return useQuery({
    queryKey: HELD_KEY(sessionId),
    queryFn: async () => heldFromApi((await posApi.heldCarts(sessionId)) ?? [], catalog),
    enabled: Boolean(sessionId),
    staleTime: 0,
  });
}

/** Sellable variants with live stock, straight from the backend. */
export async function fetchCatalog() {
  const [products, balances] = await Promise.all([posApi.products(), posApi.stockBalances()]);
  return buildCatalog(Array.isArray(products) ? products : products?.items, Array.isArray(balances) ? balances : balances?.items);
}

/** Refetched after every sale, and on demand where stock must be exact (restoring a held cart). */
export function useCatalog() {
  return useQuery({ queryKey: CATALOG_KEY, queryFn: fetchCatalog, staleTime: 30_000 });
}

const lineOf = (v) => ({
  lineId: `${v.id}`,
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
  discountPct: 0,
  discount: 0,
});

/**
 * The cart + money side of one sale. The screen shows `quote.total` (computed by the backend)
 * and never sums prices itself. A newer quote request wins: a slow earlier answer cannot
 * overwrite the total of a cart that has changed since.
 */
export function usePosSale({ sessionId, catalog = [], onSold, loadFreshCatalog }) {
  const [lines, setLines] = useState([]);
  const [invoiceDiscount, setInvoiceDiscount] = useState("");
  const [quote, setQuote] = useState({ subtotal: "0.00", discountTotal: "0.00", total: "0.00", loading: false, error: null });
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState(null);
  const sale = useMemo(() => (sessionId ? createSaleSession(sessionId) : null), [sessionId]);

  const cart = useMemo(() => lines.map((l) => ({ variantId: l.variantId, qty: l.qty })), [lines]);

  // Line discounts and the invoice discount reach the backend as ONE discount total.
  const discountCents = useMemo(() => discountMinor(lines, invoiceDiscount), [lines, invoiceDiscount]);
  const discountTotal = discountCents > 0 ? fromMinor(discountCents) : undefined;

  const runQuote = useMemo(
    () =>
      latestOnly(
        (q) => setQuote({ ...q, loading: false, error: null }),
        (e) => setQuote((q) => ({ ...q, loading: false, error: e?.message || "تعذّر حساب الإجمالي" })),
      ),
    [],
  );

  useEffect(() => {
    if (!sale || cart.length === 0) {
      runQuote.cancel();
      setQuote({ subtotal: "0.00", discountTotal: "0.00", total: "0.00", loading: false, error: null });
      return;
    }
    setQuote((q) => ({ ...q, loading: true, error: null }));
    runQuote(() => sale.quote({ cart, discountTotal }));
  }, [sale, cart, discountTotal, runQuote]);

  // The verdict is computed from the CURRENT lines (not inside setState, which runs later), so the
  // cashier is told right away why a click did nothing.
  const linesRef = useRef(lines);
  linesRef.current = lines;
  const add = useCallback((variant) => {
    if (variant.stock <= 0) return { ok: false, reason: "نافد من المخزون" };
    const existing = linesRef.current.find((l) => l.variantId === variant.id);
    if (!existing) {
      setLines((prev) => (prev.some((l) => l.variantId === variant.id) ? prev : [...prev, lineOf(variant)]));
      return { ok: true };
    }
    if (existing.qty >= variant.stock) return { ok: false, reason: `المتاح ${variant.stock} فقط` };
    setLines((prev) => prev.map((l) => (l.variantId === variant.id ? { ...l, qty: clampQty(l.qty + 1, variant.stock) } : l)));
    return { ok: true };
  }, []);

  const setQty = useCallback((lineId, value) => setLines((prev) => prev.map((l) => (l.lineId === lineId ? { ...l, qty: clampQty(value, l.stock) || 1 } : l))), []);
  const stepQty = useCallback((lineId, delta) => setLines((prev) => prev.map((l) => (l.lineId === lineId ? { ...l, qty: clampQty(l.qty + delta, l.stock) || 1 } : l))), []);
  const setLineDiscount = useCallback((lineId, pct) => setLines((prev) => prev.map((l) => (l.lineId === lineId ? { ...l, discountPct: pct, discount: +((l.price * l.qty * pct) / 100).toFixed(2) } : l))), []);
  const remove = useCallback((lineId) => setLines((prev) => prev.filter((l) => l.lineId !== lineId)), []);
  const clear = useCallback(() => {
    setLines([]);
    setInvoiceDiscount("");
    setPayError(null);
  }, []);


  /** Park the current cart on the backend and empty the screen. The cart is only cleared after the backend accepted it. */
  const hold = useCallback(
    async ({ label, customerId } = {}) => {
      if (!sessionId || cart.length === 0) throw new Error("لا توجد أصناف لتعليقها");
      const saved = await posApi.holdCart(sessionId, holdPayload({ cart, customerId, discountTotal, label }));
      setLines([]);
      setInvoiceDiscount("");
      return saved;
    },
    [sessionId, cart, discountTotal],
  );

  /**
   * Bring a held cart back. Re-checks price and stock now; deletes the parked copy ONLY after the lines are
   * on the screen, so an error can never lose the cart. A 404 on delete means it was already released.
   */
  const restore = useCallback(
    async (heldId) => {
      const cartData = await posApi.getHeldCart(heldId);
      // Stock may have changed since the screen last loaded it (another till, another cashier): ask again NOW.
      const fresh = loadFreshCatalog ? await loadFreshCatalog() : catalog;
      const r = restoreHeld(cartData, fresh);
      if (!r.canRelease) return { ...r, released: false };
      setLines(r.lines);
      setInvoiceDiscount(r.discount > 0 ? String(r.discount) : "");
      try {
        await posApi.releaseHeldCart(heldId);
      } catch (e) {
        if (e?.status !== 404) return { ...r, released: false, releaseError: e?.message || "تعذّر حذف النسخة المعلقة" };
      }
      return { ...r, released: true };
    },
    [catalog, loadFreshCatalog],
  );

  const pay = useCallback(
    async ({ tenders, customerId, cashier, customerName }) => {
      if (!sale) throw new Error("لا توجد وردية مفتوحة");
      setPaying(true);
      setPayError(null);
      try {
        const sold = await sale.pay({ cart, total: quote.total, discountTotal, customerId, tenders });
        const names = Object.fromEntries(catalog.map((v) => [v.id, v.productName]));
        const detail = await posApi.receipt(sold.receipt_id);
        const receipt = receiptFromApi(detail, { cashier, customerName, names });
        setLines([]);
        setInvoiceDiscount("");
        onSold?.(receipt);
        return receipt;
      } catch (e) {
        setPayError(e?.message || "تعذّر إتمام البيع");
        throw e;
      } finally {
        setPaying(false);
      }
    },
    [sale, cart, quote.total, discountTotal, catalog, onSold],
  );

  const scan = useCallback((value) => posApi.scan(sessionId, { identifierType: "barcode", value }), [sessionId]);

  return { lines, scan, hold, restore, quote, discountTotal, invoiceDiscount, setInvoiceDiscount, add, setQty, stepQty, setLineDiscount, remove, clear, pay, paying, payError, searchCatalog };
}
