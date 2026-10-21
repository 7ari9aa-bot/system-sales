/**
 * The sales screen sells from THIS shift's till, not from "the whole catalog".
 *
 * The generic catalog knows every variant (barcode, colour, size, image) but sums stock over all
 * warehouses and ignores the till's item groups. `GET /pos/sessions/{id}/items` is the opposite: it
 * is limited to what this till may sell, and its stock is the till's own warehouse, but it carries
 * no barcode/colour/size. So the till decides WHAT is sellable, WHAT it costs and HOW MANY are
 * there; the catalog only supplies how the variant looks. A variant the till does not list never
 * reaches the cashier, and one the catalog does not know is dropped rather than shown half-blank.
 */
import { parseMoney } from "./money";

/** Page size the server accepts at most (`limit must be between 1 and 60`). */
export const ITEMS_PAGE = 60;
/** Stop a runaway loop: more pages than this means something is wrong, not that the shop is huge. */
export const ITEMS_MAX_PAGES = 100;

export function mergeSessionItems(catalog, items) {
  const byId = new Map((catalog ?? []).map((v) => [v.id, v]));
  const out = [];
  for (const it of items ?? []) {
    const known = byId.get(it.variant_id);
    if (!known) continue;
    out.push({
      ...known,
      stock: Math.max(0, Number(it.available) || 0),
      sellPrice: parseMoney(it.unit_price).minor / 100,
    });
  }
  return out;
}

/** Every page of the till's items. `fetchPage(offset, limit)` returns `{ items, total }`. */
export async function fetchAllItems(fetchPage) {
  const all = [];
  for (let page = 0; page < ITEMS_MAX_PAGES; page += 1) {
    const res = await fetchPage(page * ITEMS_PAGE, ITEMS_PAGE);
    const rows = res?.items ?? [];
    all.push(...rows);
    const total = Number(res?.total ?? rows.length);
    if (rows.length === 0 || all.length >= total) return all;
  }
  throw new Error("قائمة أصناف الدرج لا تنتهي. أبلغ الدعم الفني قبل البيع.");
}

/** Products per request when walking the whole product list. */
export const PRODUCTS_PAGE = 200;

/**
 * Every product, page by page. The list endpoint has no `total`, so the last page is the first one
 * shorter than the page size. A single capped request would silently drop every product past the
 * cap, and the cashier could not sell it with no message; a list that never ends fails loudly.
 * `fetchPage(offset, limit)` returns the array of products for that window.
 */
export async function fetchAllProducts(fetchPage) {
  const all = [];
  for (let page = 0; page < ITEMS_MAX_PAGES; page += 1) {
    const res = await fetchPage(page * PRODUCTS_PAGE, PRODUCTS_PAGE);
    const rows = Array.isArray(res) ? res : (res?.items ?? []);
    all.push(...rows);
    if (rows.length < PRODUCTS_PAGE) return all;
  }
  throw new Error("قائمة المنتجات لا تنتهي. أبلغ الدعم الفني قبل البيع.");
}
