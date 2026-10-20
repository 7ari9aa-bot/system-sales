/**
 * Backend catalog + stock -> the variant shape the POS screen renders.
 *
 * Stock shown to the cashier = on_hand - reserved, summed across warehouses. The backend's
 * /quote does NOT check stock (only /sell does), so the screen must stop over-selling itself
 * instead of letting the cashier discover it at payment time.
 */
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
  const q = String(term ?? "").trim().toLowerCase();
  if (!q) return [];
  return catalog
    .filter((v) => [v.productName, v.sku, v.barcode, v.color, v.size].some((f) => String(f ?? "").toLowerCase().includes(q)))
    .slice(0, limit);
}
