/**
 * Typed-ish client for /api/v1/pos. Thin on purpose: transport, cookies, CSRF and
 * 401-refresh already live in lib/api.js. This file owns three guarantees:
 *
 *  1. MONEY: every amount goes through toWire(); a negative or malformed value
 *     throws BEFORE a request is made.
 *  2. RETRY SAFETY: every money-moving call needs an `intent` and sends its key as
 *     `Idempotency-Key`. The same intent re-sent = the same key = the server replays
 *     the first answer. A new deliberate sale = a new intent. (Backend allow-list:
 *     /api/v1/pos in core/idempotency.py.)
 *  3. SHAPE: obviously-wrong input (empty cart, qty <= 0, unknown tender method)
 *     is rejected locally with a clear message.
 */
import { api } from "@/lib/api";
import { toWire } from "./money";

export const BALANCES_LIMIT = 5000;
const METHODS = ["cash", "card", "wallet", "bank_transfer"];
const DIRECTIONS = ["in", "out"];
const REASONS = ["pay_in", "pay_out", "cash_drop", "float_adjust"];

/** One user intention (one Pay tap). Keep it until the call SUCCEEDS, then drop it. */
export function newIntent() {
  const rand =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  return { key: `pos-${rand}` };
}

const seg = (v) => encodeURIComponent(String(v));

function needIntent(intent) {
  if (!intent || typeof intent.key !== "string" || intent.key.length < 8) {
    throw new TypeError("posApi: a money call needs an intent (use newIntent()) so a retry cannot double-charge");
  }
  return { "Idempotency-Key": intent.key };
}

function method(m) {
  if (!METHODS.includes(m)) throw new RangeError(`posApi: unknown payment method "${m}"`);
  return m;
}

function lines(list, what = "item") {
  if (!Array.isArray(list) || list.length === 0) throw new RangeError(`posApi: at least one ${what} is required`);
  return list.map((l) => {
    if (!l?.variant_id) throw new TypeError(`posApi: every ${what} needs a variant_id`);
    if (!Number.isInteger(l.quantity) || l.quantity < 1) throw new RangeError(`posApi: ${what} quantity must be an integer >= 1`);
    return { ...l, variant_id: String(l.variant_id) };
  });
}

function tenders(list) {
  if (list == null) return undefined;
  if (!Array.isArray(list) || list.length === 0) throw new RangeError("posApi: tenders must be a non-empty list");
  return list.map((t) => ({ method: method(t.method), amount: toWire(t.amount) }));
}

const compact = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));
const opt = (v) => (v === undefined || v === null ? undefined : toWire(v));

function post(path, body, headers = {}) {
  return api(path, { method: "POST", body, headers });
}

export const posApi = {
  /* ---- setup / reads (no money, no intent) ---- */
  listProfiles: () => api("/pos/profiles"),
  listRegisters: () => api("/pos/registers"),
  listSessions: (query = "") => api(`/pos/sessions${query ? `?${query}` : ""}`),
  getSession: (id) => api(`/pos/sessions/${seg(id)}`),
  closePreview: (id) => api(`/pos/sessions/${seg(id)}/close-preview`),
  reconciliation: (id) => api(`/pos/sessions/${seg(id)}/reconciliation`),
  report: (id) => api(`/pos/sessions/${seg(id)}/report`),
  /* ---- catalog (read-only): products with variants, and stock per variant/warehouse ---- */
  products: () => api("/products?limit=500"),
  // The backend lists 200 rows by default with NO ORDER BY: past 200 variants the rest would silently show
  // stock 0 and be unsellable. Ask for a big page and let fetchCatalog() refuse a full page (see BALANCES_LIMIT).
  stockBalances: () => api(`/inventory/balances?limit=${BALANCES_LIMIT}`),
  receipts: (id) => api(`/pos/sessions/${seg(id)}/receipts`),
  receipt: (id) => api(`/pos/receipts/${seg(id)}`),
  heldCarts: (id) => api(`/pos/sessions/${seg(id)}/held-carts`),
  dailyReport: (query = "") => api(`/pos/reports/daily${query ? `?${query}` : ""}`),

  /* ---- shift ---- */
  openSession: async (registerId, { openingFloat = 0, floatsByMethod, profileId } = {}) =>
    post(
      `/pos/registers/${seg(registerId)}/sessions`,
      compact({
        opening_float: toWire(openingFloat),
        floats_by_method: floatsByMethod
          ? Object.fromEntries(Object.entries(floatsByMethod).map(([k, v]) => [method(k), toWire(v)]))
          : undefined,
        profile_id: profileId,
      }),
    ),
  closeSession: async (id, { countedCash, countedByMethod }) =>
    post(
      `/pos/sessions/${seg(id)}/close`,
      compact({
        counted_cash: toWire(countedCash),
        counted_by_method: countedByMethod
          ? Object.fromEntries(Object.entries(countedByMethod).map(([k, v]) => [method(k), toWire(v)]))
          : undefined,
      }),
    ),

  /* ---- cart ---- */
  scan: (id, { identifierType, value }) =>
    post(`/pos/sessions/${seg(id)}/scan`, { identifier_type: identifierType, value: String(value) }),
  quote: async (id, { items, discountTotal }) =>
    post(`/pos/sessions/${seg(id)}/quote`, compact({ items: lines(items), discount_total: opt(discountTotal) })),
  holdCart: async (id, { items, customerId, discountTotal, label }) =>
    post(
      `/pos/sessions/${seg(id)}/held-carts`,
      compact({ items: lines(items), customer_id: customerId, discount_total: opt(discountTotal), label }),
    ),
  getHeldCart: (heldId) => api(`/pos/held-carts/${seg(heldId)}`),
  releaseHeldCart: (heldId) => api(`/pos/held-carts/${seg(heldId)}`, { method: "DELETE" }),

  /* ---- expenses (backend/app/modules/expenses) ---- */
  expenseCategories: () => api("/expenses/categories"),
  createExpenseCategory: (name) => post("/expenses/categories", { name: String(name ?? "").trim() }),
  listExpenses: (query = "") => api(`/expenses?limit=500${query ? `&${query}` : ""}`),
  // Posting books the expense AND (if cash) the drawer pay-out: a retry must not do it twice.
  createExpense: async (payload, intent) => post("/expenses", payload, needIntent(intent)),
  voidExpense: async (id, { reason }, intent) =>
    post(`/expenses/${seg(id)}/void`, { reason: String(reason ?? "").trim() }, needIntent(intent)),

  /* ---- purchasing (backend/app/modules/purchasing) ---- */
  listSuppliers: () => api("/suppliers"),
  getSupplier: (id) => api(`/suppliers/${seg(id)}`),
  createSupplier: (body) => post("/suppliers", body),
  updateSupplier: (id, body) => api(`/suppliers/${seg(id)}`, { method: "PATCH", body }),
  listPurchaseOrders: (query = "") => api(`/purchase-orders?limit=500${query ? `&${query}` : ""}`),
  // Receiving moves stock AND cost exactly once: a retried Save must replay, not double the shelf.
  createPurchaseOrder: async (payload, intent) => post("/purchase-orders", payload, needIntent(intent)),
  receivePurchaseOrder: async (id, intent) => post(`/purchase-orders/${seg(id)}/receive`, undefined, needIntent(intent)),
  cancelPurchaseOrder: async (id, intent) => post(`/purchase-orders/${seg(id)}/cancel`, undefined, needIntent(intent)),
  listSupplierPayments: (query = "") => api(`/supplier-payments?limit=500${query ? `&${query}` : ""}`),
  createSupplierPayment: async (payload, intent) => post("/supplier-payments", payload, needIntent(intent)),
  listSupplierReturns: (query = "") => api(`/supplier-returns?limit=500${query ? `&${query}` : ""}`),
  createSupplierReturn: async (payload, intent) => post("/supplier-returns", payload, needIntent(intent)),
  acceptSupplierReturn: async (id, body, intent) => post(`/supplier-returns/${seg(id)}/accept`, body ?? {}, needIntent(intent)),
  rejectSupplierReturn: async (id, intent) => post(`/supplier-returns/${seg(id)}/reject`, undefined, needIntent(intent)),
  variantCost: (id) => api(`/variant-costs/${seg(id)}`),
  variantCostHistory: (id) => api(`/variant-costs/${seg(id)}/history`),

  /* ---- money (intent required) ---- */
  sell: async (id, { items, customerId, tenders: t, discountTotal, tenderedCash, heldCartId }, intent) => {
    const headers = needIntent(intent);
    const useHeld = heldCartId && !items;
    return post(
      `/pos/sessions/${seg(id)}/sell`,
      compact({
        items: useHeld ? undefined : lines(items),
        customer_id: customerId,
        tenders: tenders(t),
        discount_total: opt(discountTotal),
        tendered_cash: opt(tenderedCash),
        held_cart_id: heldCartId,
      }),
      headers,
    );
  },
  refund: async (id, { orderId, amount, method: m = "cash", reason, restock = false }, intent) =>
    post(
      `/pos/sessions/${seg(id)}/refunds`,
      compact({ order_id: orderId, amount: toWire(amount), method: method(m), reason, restock }),
      needIntent(intent),
    ),
  returnSale: async (id, { orderId, lines: l, restock = false }, intent) =>
    post(
      `/pos/sessions/${seg(id)}/returns`,
      { order_id: orderId, lines: lines(l, "return line"), restock },
      needIntent(intent),
    ),
  exchange: async (id, { orderId, returnLines, newLines, restock = true, tenders: t, tenderedCash }, intent) =>
    post(
      `/pos/sessions/${seg(id)}/exchanges`,
      compact({
        order_id: orderId,
        return_lines: lines(returnLines, "return line"),
        new_lines: lines(newLines, "new line"),
        restock,
        tenders: tenders(t),
        tendered_cash: opt(tenderedCash),
      }),
      needIntent(intent),
    ),
  cashMovement: async (id, { direction, reason, amount, referenceId }, intent) => {
    if (!DIRECTIONS.includes(direction)) throw new RangeError(`posApi: unknown direction "${direction}"`);
    if (!REASONS.includes(reason)) throw new RangeError(`posApi: unknown reason "${reason}"`);
    return post(
      `/pos/sessions/${seg(id)}/cash-movements`,
      compact({ direction, reason, amount: toWire(amount), reference_id: referenceId }),
      needIntent(intent),
    );
  },
  handover: async (id, { toUserId, countedCash, note }, intent) =>
    post(
      `/pos/sessions/${seg(id)}/handover`,
      compact({ to_user_id: toUserId, counted_cash: toWire(countedCash), note }),
      needIntent(intent),
    ),
};
