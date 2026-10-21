/**
 * Backend stock rows -> what the inventory screens print. The server already decided everything
 * that is a RULE (the status, the totals, the value of the shelf); this file only renames and types.
 *
 * Two traps are handled here on purpose:
 *  - MONEY arrives as TEXT ("40.50"). It is parsed once, here, and never summed on the client: the
 *    totals come from /pos/stock/summary, which covers EVERY variant, not just the loaded page.
 *  - An UNKNOWN cost is `null`, not 0. A zero would value the shelf at nothing and make every margin
 *    look like 100%. It stays null all the way to the cell, which prints "غير معروفة".
 */

/** The page size the screen asks for. One shop first: 1000 is the server's ceiling. */
export const STOCK_LIMIT = 1000;

const STATUSES = ["in", "low", "out"];

function amount(text) {
  if (text === null || text === undefined) return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/** "اللون / المقاس" from the variant's options. Unknown option keys are kept, not dropped. */
function describeOptions(options) {
  const o = options && typeof options === "object" ? options : {};
  const { color = "", size = "", ...rest } = o;
  return { color: String(color), size: String(size), extra: Object.values(rest).map(String) };
}

export function stockRowFromApi(raw) {
  const { color, size, extra } = describeOptions(raw.options);
  const status = STATUSES.includes(raw.status) ? raw.status : "in";
  return {
    id: raw.variant_id,
    productId: raw.product_id,
    productName: raw.product_title,
    category: raw.category ?? "",
    categoryId: raw.category_id ?? null,
    sku: raw.sku ?? "",
    barcode: raw.barcode ?? "",
    color,
    // A variant with an option other than colour/size still has to be tellable apart on screen.
    size: [size, ...extra].filter(Boolean).join(" / "),
    sellPrice: amount(raw.price) ?? 0,
    buyPrice: amount(raw.avg_cost), // null = unknown
    costKnown: raw.avg_cost !== null && raw.avg_cost !== undefined,
    stock: Number(raw.on_hand) || 0,
    reserved: Number(raw.reserved) || 0,
    threshold: Number(raw.reorder_level) || 0, // 0 = no alert configured
    status,
    costValue: amount(raw.stock_cost_value),
    retailValue: amount(raw.stock_retail_value) ?? 0,
  };
}

export function stockSummaryFromApi(raw) {
  return {
    variants: Number(raw?.variants) || 0,
    pieces: Number(raw?.pieces) || 0,
    out: Number(raw?.out) || 0,
    low: Number(raw?.low) || 0,
    alerts: Number(raw?.alerts) || 0,
    costValue: amount(raw?.cost_value) ?? 0,
    retailValue: amount(raw?.retail_value) ?? 0,
    unknownCost: Number(raw?.unknown_cost_variants) || 0,
  };
}

/** Query string for GET /pos/stock. Empty filters are left out; the server rejects a bad status. */
export function stockQuery({ term = "", categoryId = "", status = "", offset = 0, limit = STOCK_LIMIT } = {}) {
  const p = new URLSearchParams();
  if (term.trim()) p.set("term", term.trim());
  if (categoryId) p.set("category_id", categoryId);
  if (STATUSES.includes(status)) p.set("status", status);
  p.set("limit", String(limit));
  if (offset) p.set("offset", String(offset));
  return p.toString();
}

/** A cell for a cost that may be unknown. */
export function costLabel(value, format) {
  return value === null || value === undefined ? "غير معروفة" : format(value);
}
