// The words on a number card, in the owner's language. The server sends internal names
// ("delivered_revenue", unit "money", window "15d"); the owner reads plain shop words.
// A closed table does the translating; a name it does not know is never shown raw.

// internal metric name -> the key of its translation
const METRIC_KEYS = {
  orders_placed: "kpi.metric.orders_placed",
  delivered_revenue: "kpi.metric.delivered_revenue",
  shipped_orders: "kpi.metric.shipped_orders",
  collected_revenue: "kpi.metric.collected_revenue",
  refund_amount: "kpi.metric.refund_amount",
  net_revenue: "kpi.metric.net_revenue",
  aov: "kpi.metric.aov",
  pos_sales_total: "kpi.metric.pos_sales_total",
  pos_invoice_count: "kpi.metric.pos_invoice_count",
  pos_returns_total: "kpi.metric.pos_returns_total",
  pos_net_sales: "kpi.metric.pos_net_sales",
  stock_total_on_hand: "kpi.metric.stock_total_on_hand",
  stock_total_available: "kpi.metric.stock_total_available",
  stock_tracked_variants: "kpi.metric.stock_tracked_variants",
  stock_untracked_variants: "kpi.metric.stock_untracked_variants",
  stock_low_variants: "kpi.metric.stock_low_variants",
  stock_out_variants: "kpi.metric.stock_out_variants",
  stock_stagnant_variants: "kpi.metric.stock_stagnant_variants",
  expenses_total: "kpi.metric.expenses_total",
  expenses_count: "kpi.metric.expenses_count",
  gross_profit: "kpi.metric.gross_profit",
  net_profit: "kpi.metric.net_profit",
  cost_of_goods: "kpi.metric.cost_of_goods",
  purchased_total: "kpi.metric.purchased_total",
  purchase_orders_received: "kpi.metric.purchase_orders_received",
  products_sold_variants: "kpi.metric.products_sold_variants",
  customers_new: "kpi.metric.customers_new",
  customers_returning: "kpi.metric.customers_returning",
  customers_contacted: "kpi.metric.customers_contacted",
  customer_total_spent: "kpi.metric.customer_total_spent",
  customers_who_ordered: "kpi.metric.customers_who_ordered",
  days_since_last_order: "kpi.metric.days_since_last_order",
  total_owed: "kpi.metric.total_owed",
  conversations_total: "kpi.metric.conversations_total",
  inbound_messages_total: "kpi.metric.inbound_messages_total",
  new: "kpi.metric.new",
  returning: "kpi.metric.returning",
  inventory_total_units: "kpi.metric.inventory_total_units",
  inventory_total_value: "kpi.metric.inventory_total_value",
  inventory_dead_stock_count: "kpi.metric.inventory_dead_stock_count",
  inventory_dead_stock_value: "kpi.metric.inventory_dead_stock_value",
  inventory_low_stock_count: "kpi.metric.inventory_low_stock_count",
  inventory_expiring_lots: "kpi.metric.inventory_expiring_lots",
  inventory_expired_lots: "kpi.metric.inventory_expired_lots",
  inventory_pending_reorders: "kpi.metric.inventory_pending_reorders",
};

/** Every metric name the server can send a card for. The test checks the server's own list against it. */
export const KNOWN_METRICS = Object.keys(METRIC_KEYS);

/** The label under the number. An unknown name becomes plain words (underscores to spaces) rather
 *  than leaking the identifier, and an empty one becomes an empty string. */
export function metricLabel(metric, t) {
  const name = typeof metric === "string" ? metric.trim() : "";
  if (!name) return "";
  const key = METRIC_KEYS[name];
  if (key) return t(key);
  return name.replace(/_/g, " ");
}

/** The small unit next to the number. "money" and "count" are internal words and say nothing the
 *  label does not already say (the shop's currency is not on the card, so none is guessed), so they
 *  are dropped. A real currency or unit sent by the server (e.g. "EGP") is shown as it is. */
export function unitLabel(unit) {
  const u = typeof unit === "string" ? unit.trim() : "";
  if (!u) return "";
  if (/^(money|count|orders|number|amount|currency)$/i.test(u)) return "";
  return u;
}

/** "15d" -> "15 days" in the owner's language; anything else is shown as it came. */
export function windowLabel(window, t) {
  const w = typeof window === "string" ? window.trim() : "";
  if (!w) return "";
  const m = /^(\d+)d$/.exec(w);
  if (!m) return w;
  const days = Number(m[1]);
  if (days === 0) return t("kpi.window.today");
  if (days === 1) return t("kpi.window.one_day");
  return t("kpi.window.days", { n: days });
}

const SAFE_REASONS = ["si_response_invalid", "unsourced_claim", "unverified_commercial_claim", "injection_risk", "cross_tenant_request", "handover", "unknown_agent_kind"];
const QUALITY = ["partial", "immature", "stale", "insufficient", "conflicting"];

/** The line under an answer the server held back or flagged. The server sends an internal reason
 *  ("safe response: si_response_invalid", "data quality: partial"); the owner reads a plain sentence.
 *  A reason the table does not know is never shown raw: it becomes a general, honest sentence. */
export function noticeText(message, t) {
  const text = typeof message === "string" ? message.trim() : "";
  if (!text) return "";
  const safe = /^safe response:\s*([a-z_:]+)$/i.exec(text);
  if (safe) {
    const reason = safe[1].toLowerCase();
    return SAFE_REASONS.includes(reason) ? t(`notice.safe.${reason}`) : t("notice.safe.unknown");
  }
  const quality = /^data quality:\s*([a-z_]+)$/i.exec(text);
  if (quality) {
    const state = quality[1].toLowerCase();
    return QUALITY.includes(state) ? t(`notice.quality.${state}`) : t("notice.quality.unknown");
  }
  return text;
}
