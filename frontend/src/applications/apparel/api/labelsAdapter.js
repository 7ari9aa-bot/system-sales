/**
 * Label printing: group the stock list's variants into products, and turn a received purchase
 * invoice into per-variant label counts. Pure functions over what the backend returned; nothing here
 * invents a barcode, a price or a quantity.
 */

export const MAX_LABELS_PER_VARIANT = 99;

/** Stock rows (see stockRowFromApi) -> one row per product with its variants, for the labels table. */
export function labelProducts(stockRows) {
  const byProduct = new Map();
  for (const r of stockRows ?? []) {
    const key = r.productId ?? r.productName;
    if (!byProduct.has(key)) {
      byProduct.set(key, {
        id: key,
        name: r.productName,
        sku: r.sku,
        brand: "",
        category: r.category,
        sellPrice: r.sellPrice,
        variants: [],
      });
    }
    byProduct.get(key).variants.push({ id: r.id, color: r.color, size: r.size, barcode: r.barcode, sku: r.sku, price: r.sellPrice, stock: r.stock });
  }
  return [...byProduct.values()].map((p) => ({
    ...p,
    sku: p.variants[0]?.sku ?? p.sku,
    colors: [...new Set(p.variants.map((v) => v.color).filter(Boolean))],
    sizes: [...new Set(p.variants.map((v) => v.size).filter(Boolean))],
    variantsCount: p.variants.length,
    totalStock: p.variants.reduce((s, v) => s + v.stock, 0),
  }));
}

/** Clamp a typed quantity to a printable whole number. */
export const clampLabelQty = (value) => Math.max(0, Math.min(MAX_LABELS_PER_VARIANT, Math.floor(Number(value)) || 0));

/**
 * Label counts for the variants on a purchase invoice: { variantId: qty }. Only a RECEIVED invoice
 * counts (a draft has not brought pieces into the shop); a line whose variant has no barcode is skipped
 * and reported, since a label without a barcode cannot be scanned.
 */
export function countsFromOrder(order, variants) {
  const counts = {};
  const skipped = [];
  if (!order || order.receipt !== "received") return { counts, skipped, pieces: 0 };
  for (const line of order.items ?? []) {
    const variant = variants.get(line.variantId);
    if (!variant) continue;
    if (!variant.barcode) {
      skipped.push(line.variantId);
      continue;
    }
    counts[line.variantId] = clampLabelQty((counts[line.variantId] ?? 0) + Number(line.qty));
  }
  return { counts, skipped, pieces: Object.values(counts).reduce((s, n) => s + n, 0) };
}
