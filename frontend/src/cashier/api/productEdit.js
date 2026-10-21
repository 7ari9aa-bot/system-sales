// Edit an existing product against the backend: read it into the form's shape, and turn the form back into
// the SMALLEST set of backend calls. Pure functions, so they are tested without a network.

import { toWire } from "./money";

const text = (v) => String(v ?? "").trim();

/** A backend product (with its variants and barcodes) as the editor form's `product`. */
export function productToForm(product, identifiersByVariant = {}) {
  const variants = (product.variants ?? []).map((v) => ({
    id: v.id,
    sku: v.sku ?? "",
    color: v.option_values?.color ?? "",
    size: v.option_values?.size ?? "",
    sellPrice: v.price == null ? "" : String(v.price),
    barcode: identifiersByVariant[v.id] ?? "",
    isActive: v.is_active !== false,
  }));
  const uniq = (xs) => [...new Set(xs.filter(Boolean))];
  return {
    id: product.id,
    name: product.title ?? "",
    description: product.description ?? "",
    categoryId: product.category_id ?? "",
    brandId: product.brand_id ?? "",
    sku: variants[0]?.sku ?? "",
    colors: uniq(variants.map((v) => v.color)),
    sizes: uniq(variants.map((v) => v.size)),
    variants,
    images: product.images ?? [],
  };
}

/**
 * The calls an edit needs. `before` is the form's shape from productToForm; `after` is what the user submitted.
 * Only what changed is sent. Rows without an `id` are new combinations.
 */
export function planProductEdit(before, after) {
  const product = {};
  if (text(after.name) !== text(before.name)) product.title = text(after.name);
  if (text(after.description) !== text(before.description)) product.description = text(after.description) || null;
  if ((after.categoryId || "") !== (before.categoryId || "")) product.category_id = after.categoryId || null;
  if ((after.brandId || "") !== (before.brandId || "")) product.brand_id = after.brandId || null;

  const byId = new Map(before.variants.map((v) => [v.id, v]));
  const variantPatches = [];
  const newVariants = [];
  const newBarcodes = [];
  for (const row of after.variants) {
    if (!row.id || !byId.has(row.id)) {
      newVariants.push(row);
      continue;
    }
    const old = byId.get(row.id);
    const patch = {};
    if (text(row.sku) !== text(old.sku)) patch.sku = text(row.sku);
    if (String(row.sellPrice) !== String(old.sellPrice)) patch.price = toWire(row.sellPrice);
    if (patch.sku !== undefined || patch.price !== undefined) variantPatches.push({ id: row.id, patch });
    if (text(row.barcode) && text(row.barcode) !== text(old.barcode)) newBarcodes.push({ variantId: row.id, value: text(row.barcode) });
  }
  const empty = !Object.keys(product).length && !variantPatches.length && !newVariants.length && !newBarcodes.length;
  return { product, variantPatches, newVariants, newBarcodes, empty };
}
