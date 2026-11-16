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
};

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
