/**
 * Backend catalog + stock -> the variant shape the POS screen renders.
 *
 * Stock shown to the cashier = on_hand - reserved, summed across warehouses. The backend's
 * /quote does NOT check stock (only /sell does), so the screen must stop over-selling itself
 * instead of letting the cashier discover it at payment time.
 */
import { foldCode, foldedIncludes } from "@/cashier/lib/searchText";
import { parseMoney } from "./money";

const price = (wire) => parseMoney(wire).minor / 100;

export function available(balances, variantId) {
  const total = (balances ?? [])
    .filter((b) => b.variant_id === variantId)
    .reduce((sum, b) => sum + (Number(b.on_hand) || 0) - (Number(b.reserved) || 0), 0);
  return Math.max(0, total);
}

export function variantFromApi(product, variant, balances) {
  const opts = variant.option_values ?? {};
  return {
    id: variant.id,
    productId: product.id,
    productName: product.title,
    sku: variant.sku,
    barcode: variant.barcode ?? "",
    color: opts.color ?? "",
    size: opts.size ?? variant.title ?? "",
    brand: "",
    image: product.images?.[0]?.url ?? null,
    stock: available(balances, variant.id),
    sellPrice: price(variant.price),
  };
}

export function buildCatalog(products, balances) {
  return (products ?? [])
    .filter((p) => p.status === "active")
    .flatMap((p) => (p.variants ?? []).filter((v) => v.is_active).map((v) => variantFromApi(p, v, balances)));
}

export function searchCatalog(catalog, term, limit = 20) {
  const q = String(term ?? "").trim();
  if (!q) return [];
  // Forgiving on Arabic spelling and digits ("احمر" finds "أحمر"); see lib/searchText.js.
  return catalog
    .filter((v) => [v.productName, v.sku, v.barcode, v.color, v.size].some((f) => foldedIncludes(f ?? "", q)))
    .slice(0, limit);
}

/**
 * What a typed or scanned term means at the till, when the backend scan did not answer.
 *
 * An EXACT code (barcode, then SKU, compared after the same folding the search uses) always wins
 * over a partial match, so a short code that is a piece of a longer one never selects two items.
 * Only when no code matches exactly does it fall back to a partial search. An item that matches
 * but has no stock says so ("soldout") instead of reading as "not found".
 * Returns { kind: "one" | "many" | "soldout" | "none", variant? }.
 */
export function resolveTypedCode(catalog, term) {
  const q = foldCode(String(term ?? ""));
  if (!q) return { kind: "none" };
  const sellable = (v) => Number(v.stock) > 0;
  for (const field of ["barcode", "sku"]) {
    const exact = (catalog ?? []).filter((v) => foldCode(v[field] ?? "") === q);
    if (exact.length === 0) continue;
    const inStock = exact.filter(sellable);
    if (inStock.length === 1) return { kind: "one", variant: inStock[0] };
    if (inStock.length > 1) return { kind: "many" };
    return { kind: "soldout", variant: exact[0] };
  }
  const partial = searchCatalog(catalog ?? [], term, 50);
  const inStock = partial.filter(sellable);
  if (inStock.length === 1) return { kind: "one", variant: inStock[0] };
  if (inStock.length > 1) return { kind: "many" };
  if (partial.length > 0) return { kind: "soldout", variant: partial[0] };
  return { kind: "none" };
}
