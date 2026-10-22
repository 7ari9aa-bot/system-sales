import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BALANCES_LIMIT, posApi } from "./posApi";
import { needsApproval } from "./approval";
import { buildCatalog, searchCatalog } from "./catalogAdapter";
import { fetchAllItems, fetchAllProducts, fetchAllStock, mergeSessionItems, withBarcodes } from "./sessionCatalog";
import { clampQty, restoreRemovedLine } from "./checkout";
import { createSaleSession } from "./saleSession";
import { receiptFromApi } from "./receiptAdapter";
import { sellableCustomers } from "./customerRule";
import { heldFromApi, holdPayload, restoreHeld } from "./heldCarts";
import { rowFromDetail, saleReceipts } from "./salesLog";
import { invoiceFromApi, returnsOf } from "./invoiceDetail";
import { returnRows } from "./returnsLog";
import { exchangeRows } from "./exchangesLog";
import { salesRows, topProductRows } from "./salesReport";
import { periodRange } from "@/cashier/lib/period";
import { fromMinor } from "./money";
import { invoiceDiscountMinor, latestOnly } from "./latest";

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
  const [products, balances, stock] = await Promise.all([
    posApi.products(),
    posApi.stockBalances(),
    fetchAllStock((offset, limit) => posApi.stockPage(offset, limit)),
  ]);
  const rows = Array.isArray(balances) ? balances : balances?.items;
  // A page exactly as big as the limit means the list was probably cut: selling from it would show real
  // stock as 0. Fail loudly instead of letting the cashier lose sales without any message.
  if (Array.isArray(rows) && rows.length >= BALANCES_LIMIT) {
    throw new Error(`قائمة الأرصدة وصلت للحد الأقصى (${BALANCES_LIMIT}) وقد تكون ناقصة. أبلغ الدعم الفني قبل البيع.`);
  }
  // The product list carries no barcode; the stock view does (purchases, suppliers and supplier returns
  // search this catalog by scanned code).
  return withBarcodes(buildCatalog(Array.isArray(products) ? products : products?.items, rows), stock);
}

/**
 * What THIS shift's till may sell: item groups, warehouse stock and ladder price from the server,
 * looks (barcode/colour/size) from the catalog. Use this on the sales screen; the plain
 * `useCatalog` is for screens that really mean "everything, every warehouse".
 */
export const SESSION_CATALOG_KEY = (sessionId) => ["cashier", "catalog", "session", sessionId];
export async function fetchSessionCatalog(sessionId) {
  // Stock and price come from the till's own paged item list, so the shop-wide balances are NOT
  // fetched here: they are not needed, and their 5,000-row cap would otherwise stop a shop with
  // a big catalogue from selling at all. Only the looks (name, barcode, colour, size) come from
  // the product list; `mergeSessionItems` replaces stock and price with the till's figures.
  const [products, items, stock] = await Promise.all([
    fetchAllProducts((offset, limit) => posApi.productsPage(offset, limit)),
    fetchAllItems((offset, limit) => posApi.sessionItems(sessionId, offset, limit)),
    fetchAllStock((offset, limit) => posApi.stockPage(offset, limit)),
  ]);
  // The product list carries no barcode; the stock view does. Without it a scanned code finds nothing
  // on the exchange screen (and the invoice table prints a blank cell).
  const looks = withBarcodes(buildCatalog(products, []), stock);
  return mergeSessionItems(looks, items);
}
export function useSessionCatalog(sessionId) {
  return useQuery({
    queryKey: SESSION_CATALOG_KEY(sessionId),
    queryFn: () => fetchSessionCatalog(sessionId),
    enabled: Boolean(sessionId),
    staleTime: 30_000,
  });
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

  // Each line carries its own discount percentage to the server (stored on the sale line, so a
  // return refunds what THAT line paid).
  const cart = useMemo(() => lines.map((l) => ({ variantId: l.variantId, qty: l.qty, discountPct: l.discountPct })), [lines]);

  // `discountTotal` is the INVOICE-level discount only: the server adds the lines' own discounts,
  // so sending the combined figure would count them twice. The screen shows the server's quote.
  const invoiceCents = useMemo(() => invoiceDiscountMinor(invoiceDiscount), [invoiceDiscount]);
  const discountTotal = invoiceCents > 0 ? fromMinor(invoiceCents) : undefined;

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
  /**
   * Undo a delete: put the SAME line back (its quantity and discount) where it was, not a fresh one-piece line at the end.
   * Stock is re-read from the live catalog: it may have dropped since, so the quantity is clamped, never over-sold.
   */
  const restoreLine = useCallback((line, index, liveStock = line.stock) => {
    const r = restoreRemovedLine(linesRef.current, line, index, liveStock);
    if (r.ok) setLines(r.lines);
    return { ok: r.ok, reason: r.reason, clamped: r.clamped };
  }, []);
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
    async ({ tenders, customerId, cashier, customerName, approval }) => {
      if (!sale) throw new Error("لا توجد وردية مفتوحة");
      setPaying(true);
      setPayError(null);
      try {
        const { detail } = await sale.pay({ cart, total: quote.total, discountTotal, customerId, tenders, approval });
        const names = Object.fromEntries(catalog.map((v) => [v.id, v.productName]));
        const receipt = receiptFromApi(detail, { cashier, customerName, names });
        setLines([]);
        setInvoiceDiscount("");
        onSold?.(receipt);
        return receipt;
      } catch (e) {
        // "Needs a manager" is not a payment failure: the screen opens the approval box instead.
        setPayError(needsApproval(e) ? null : e?.message || "تعذّر إتمام البيع");
        throw e;
      } finally {
        setPaying(false);
      }
    },
    [sale, cart, quote.total, discountTotal, catalog, onSold],
  );

  const scan = useCallback((value) => posApi.scan(sessionId, { identifierType: "barcode", value }), [sessionId]);

  return { lines, scan, hold, restore, quote, discountTotal, invoiceDiscount, setInvoiceDiscount, add, setQty, stepQty, setLineDiscount, remove, restoreLine, clear, pay, paying, payError, searchCatalog };
}

/**
 * Every sale receipt of one shift, completed with its detail (total, pieces, payment, return state).
 * The list endpoint only has number/time/returned units, so details are read a few at a time.
 */
export function useShiftSales(sessionId, { cashier = "" } = {}) {
  return useQuery({
    queryKey: ["cashier", "shift-sales", sessionId, cashier],
    enabled: Boolean(sessionId),
    staleTime: 10_000,
    queryFn: async () => {
      const list = saleReceipts((await posApi.receipts(sessionId)) ?? []);
      const rows = [];
      for (let i = 0; i < list.length; i += 6) {
        const batch = await Promise.all(list.slice(i, i + 6).map((r) => posApi.receipt(r.id)));
        rows.push(...batch.map((d) => rowFromDetail(d, { cashier })));
      }
      return rows.sort((a, b) => String(b.date).localeCompare(String(a.date)));
    },
  });
}

/** One sale with its returns. `sessionId` (in the link) lets us find the return receipts of the same order. */
export function useInvoice(receiptId, sessionId, { cashier = "" } = {}) {
  return useQuery({
    queryKey: ["cashier", "invoice", receiptId, sessionId, cashier],
    enabled: Boolean(receiptId),
    staleTime: 5_000,
    queryFn: async () => {
      const sale = await posApi.receipt(receiptId);
      const list = sessionId ? ((await posApi.receipts(sessionId)) ?? []) : [];
      const mine = list.filter((r) => r.kind === "return" && r.order_id === sale.order.id);
      const details = Object.fromEntries(await Promise.all(mine.map(async (r) => [r.id, await posApi.receipt(r.id)])));
      return invoiceFromApi(sale, { returns: returnsOf(sale.order.id, list, details), cashier });
    },
  });
}

/** Sales of the OPEN shift (the only ones the backend lets us return), newest first, with number + total. */
export function useReturnableSales(sessionId) {
  return useQuery({
    queryKey: ["cashier", "returnable", sessionId],
    enabled: Boolean(sessionId),
    staleTime: 0,
    queryFn: async () => {
      const list = saleReceipts((await posApi.receipts(sessionId)) ?? []);
      const rows = [];
      for (let i = 0; i < list.length; i += 6) {
        const batch = await Promise.all(list.slice(i, i + 6).map((r) => posApi.receipt(r.id)));
        rows.push(...batch);
      }
      return rows.sort((a, b) => String(b.receipt.issued_at).localeCompare(String(a.receipt.issued_at)));
    },
  });
}

/** Fewest characters the server accepts for a receipt search (it answers 422 below this). */
export const RECEIPT_SEARCH_MIN = 3;

/**
 * Find an original sale on ANY shift by its number. A return does not have to be made on the
 * shift that sold the goods; the refund is settled on the shift that is open now. The server
 * counts units already returned across every shift, so each result carries a detail the
 * return screen can use exactly like one from the open shift's own list.
 */
export function useReceiptSearch(term) {
  const q = String(term ?? "").trim();
  return useQuery({
    queryKey: ["cashier", "receipt-search", q],
    enabled: q.length >= RECEIPT_SEARCH_MIN,
    staleTime: 0,
    queryFn: async () => {
      const found = saleReceipts((await posApi.searchReceipts(q)) ?? []);
      return Promise.all(found.map((r) => posApi.receipt(r.id)));
    },
  });
}

/** Every return receipt of every shift (list endpoint only), linked to its original invoice. */
export async function fetchReturnsLog(client = posApi) {
  const sessions = (await client.listSessions()) ?? [];
  const lists = await Promise.all(sessions.map(async (s) => ((await client.receipts(s.id)) ?? []).map((r) => ({ ...r, session_id: r.session_id ?? s.id }))));
  const all = lists.flat();
  const saleByOrder = new Map(all.filter((r) => r.kind === "sale").map((r) => [r.order_id, r.id]));
  const returns = all.filter((r) => r.kind === "return");
  const details = {};
  for (let i = 0; i < returns.length; i += 6) {
    const batch = await Promise.all(returns.slice(i, i + 6).map((r) => client.receipt(r.id)));
    batch.forEach((d, j) => { details[returns[i + j].id] = d; });
  }
  return returnRows(all, details).map((r) => ({ ...r, saleReceiptId: saleByOrder.get(r.invoiceId) }));
}

/** Every exchange of every shift: the new sale receipts that carry the stored link, with both halves read. */
export async function fetchExchangesLog(client = posApi) {
  const sessions = (await client.listSessions()) ?? [];
  const lists = await Promise.all(sessions.map(async (s) => ((await client.receipts(s.id)) ?? []).map((r) => ({ ...r, session_id: r.session_id ?? s.id }))));
  const all = lists.flat();
  const ids = all.filter((r) => r.kind === "sale" && r.exchange_return_receipt_id).flatMap((r) => [r.id, r.exchange_return_receipt_id]);
  const details = {};
  for (let i = 0; i < ids.length; i += 6) {
    const batch = await Promise.all(ids.slice(i, i + 6).map((id) => client.receipt(id)));
    batch.forEach((d, j) => { details[ids[i + j]] = d; });
  }
  return exchangeRows(all, details);
}

export function useExchangesLog() {
  return useQuery({ queryKey: ["cashier", "exchanges-log"], staleTime: 0, queryFn: () => fetchExchangesLog() });
}

/** Sales per shop day for a period (the backend counts each day from the receipts). */
export function useSalesReport(period) {
  const { since, until } = periodRange(period);
  return useQuery({
    queryKey: ["cashier", "sales-report", since, until],
    staleTime: 0,
    queryFn: async () => salesRows((await posApi.salesReport(since, until)) ?? []),
  });
}

/** Best sellers for a period (ranked by net revenue on the server). */
export function useTopProducts(period) {
  const { since, until } = periodRange(period);
  return useQuery({
    queryKey: ["cashier", "top-products", since, until],
    staleTime: 0,
    queryFn: async () => topProductRows((await posApi.topProducts(since, until)) ?? []),
  });
}

export function useReturnsLog() {
  return useQuery({ queryKey: ["cashier", "returns-log"], staleTime: 0, queryFn: () => fetchReturnsLog() });
}

/** The profile this shift runs under (null when the shift has none): the source of require_customer. */
export function useShiftProfile(profileId) {
  return useQuery({
    queryKey: ["cashier", "profile", profileId],
    enabled: Boolean(profileId),
    staleTime: 60_000,
    queryFn: async () => ((await posApi.listProfiles()) ?? []).find((p) => p.id === profileId) ?? null,
  });
}

/** Customers matching what the cashier typed (name or phone). Off until there is something to search. */
export function useCustomerSearch(term) {
  const t = (term ?? "").trim();
  return useQuery({
    queryKey: ["cashier", "customer-search", t],
    enabled: t.length >= 2,
    staleTime: 15_000,
    queryFn: async () => sellableCustomers(await posApi.searchCustomers(t)),
  });
}
