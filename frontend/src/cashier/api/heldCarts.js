import { cartItems, clampQty } from "./checkout";

const FALLBACK_LABEL = "فاتورة معلقة";

/** Held carts for the picker: oldest first, with names and piece counts resolved from the catalog. */
export function heldFromApi(carts, catalog) {
  const byId = new Map(catalog.map((v) => [v.id, v]));
  return [...carts]
    .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
    .map((c) => ({
      id: c.id,
      label: (c.label || "").trim() || FALLBACK_LABEL,
      createdAt: c.created_at,
      discount: c.discount_total ?? "0.00",
      pieces: c.items.reduce((s, i) => s + i.quantity, 0),
      lines: c.items.map((i) => ({ variantId: i.variant_id, qty: i.quantity, name: byId.get(i.variant_id)?.productName ?? "صنف غير متاح" })),
    }));
}

/**
 * Turns a held cart back into cart lines. The backend keeps no price and reserves no stock when a
 * cart is held, so everything is re-checked against the catalog as it is NOW: the price is today's,
 * a quantity above today's stock is cut, and an item that is sold out or gone is dropped. Whatever
 * changed is reported so the cashier is told instead of finding out at the till.
 * `canRelease` is false when nothing could be restored: the held cart must not be deleted then.
 */
export function restoreHeld(cart, catalog) {
  const byId = new Map(catalog.map((v) => [v.id, v]));
  const wanted = new Map();
  const pctOf = new Map(); // the per-line discount the cashier typed travels with the held cart
  for (const i of cart.items) {
    wanted.set(i.variant_id, (wanted.get(i.variant_id) ?? 0) + i.quantity);
    const pct = Number(i.discount_pct);
    if (Number.isFinite(pct) && pct > 0) pctOf.set(i.variant_id, Math.min(100, pct));
  }

  const lines = [];
  const dropped = [];
  const adjusted = [];
  for (const [variantId, qty] of wanted) {
    const v = byId.get(variantId);
    if (!v) {
      dropped.push({ variantId, name: "صنف غير متاح", reason: "unavailable" });
      continue;
    }
    if (v.stock <= 0) {
      dropped.push({ variantId, name: v.productName, reason: "out_of_stock" });
      continue;
    }
    const got = clampQty(qty, v.stock);
    if (got < qty) adjusted.push({ name: v.productName, wanted: qty, got });
    lines.push({
      lineId: String(v.id),
      variantId: v.id,
      code: v.sku,
      barcode: v.barcode,
      name: v.productName,
      color: v.color,
      size: v.size,
      stock: v.stock,
      price: v.sellPrice,
      qty: got,
      discountPct: pctOf.get(variantId) ?? 0,
      discount: +((v.sellPrice * got * (pctOf.get(variantId) ?? 0)) / 100).toFixed(2),
    });
  }
  return { lines, dropped, adjusted, discount: Number(cart.discount_total) || 0, canRelease: lines.length > 0 };
}

/** What goes to POST /held-carts. Items use the API's shape (variant_id/quantity), never the screen's. */
export function holdPayload({ cart, customerId, discountTotal, label }) {
  if (!cart.length) throw new Error("لا توجد أصناف لتعليقها");
  return { items: cartItems(cart), customerId, discountTotal, label: (label ?? "").trim() || undefined };
}
