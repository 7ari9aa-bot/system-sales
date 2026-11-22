// Edit an existing product against the backend: read it into the form's shape, and turn the form back into
// the SMALLEST set of backend calls. Pure functions, so they are tested without a network.

import { toWire } from "./money";
import { materialText } from "@/cashier/lib/material";

const text = (v) => String(v ?? "").trim();

/** A backend product (with its variants and barcodes) as the editor form's `product`. */
export function productToForm(product, identifiersByVariant = {}, identifierIdsByVariant = {}) {
  const variants = (product.variants ?? []).map((v) => ({
    id: v.id,
    sku: v.sku ?? "",
    color: v.option_values?.color ?? "",
    size: v.option_values?.size ?? "",
    sellPrice: v.price == null ? "" : String(v.price),
    barcode: identifiersByVariant[v.id] ?? "",
    // The stored code's own id, so correcting it can replace that row instead of piling a second one on.
    barcodeId: identifierIdsByVariant[v.id] ?? "",
    isActive: v.is_active !== false,
  }));
  const uniq = (xs) => [...new Set(xs.filter(Boolean))];
  return {
    id: product.id,
    name: product.title ?? "",
    description: product.description ?? "",
    categoryId: product.category_id ?? "",
    brandId: product.brand_id ?? "",
    season: product.season ?? "",
    material: materialText(product.material),
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
  if (text(after.season) !== text(before.season)) product.season = text(after.season) || null;
  // الخامة بتتقارن وتتبعت بعد التشذيب: الفاضي بيتبعت null (يمسح الخامة)، والنص "null" مش خامة.
  if (materialText(after.material) !== materialText(before.material)) product.material = materialText(after.material) || null;

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
    if (text(row.barcode) && text(row.barcode) !== text(old.barcode)) {
      // A variant that already carries a code is being corrected: the old row goes once the new one is filed.
      newBarcodes.push({ variantId: row.id, value: text(row.barcode), ...(old.barcodeId ? { replacesId: old.barcodeId } : {}) });
    }
  }
  const empty = !Object.keys(product).length && !variantPatches.length && !newVariants.length && !newBarcodes.length;
  return { product, variantPatches, newVariants, newBarcodes, empty };
}

/**
 * What a failed product load means. Only a 404 says the product is gone: a 503 right after a deploy, a
 * dropped connection or a 500 must never read as "the product was deleted" to the owner.
 */
export function editLoadProblem(error) {
  const status = error?.status;
  if (status === 404) return "missing";
  if (status === 401 || status === 403) return "forbidden";
  return "temporary";
}

/** Retry only a temporary failure, and only a few times: a missing product or a refusal will not change. */
export function shouldRetryEditLoad(failureCount, error) {
  return editLoadProblem(error) === "temporary" && failureCount < 3;
}
