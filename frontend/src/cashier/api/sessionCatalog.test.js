import { describe, expect, it, vi } from "vitest";
import { ITEMS_MAX_PAGES, ITEMS_PAGE, PRODUCTS_PAGE, STOCK_PAGE, fetchAllItems, fetchAllProducts, fetchAllStock, mergeSessionItems, withBarcodes } from "./sessionCatalog";

const v = (id, over = {}) => ({ id, productName: `P${id}`, sku: `S${id}`, barcode: `B${id}`, color: "red", size: "M", stock: 99, sellPrice: 1, ...over });
const item = (id, over = {}) => ({ variant_id: id, title: `P${id}`, sku: `S${id}`, unit_price: "10.50", available: 4, ...over });

describe("mergeSessionItems: the till decides what is sold, the catalog how it looks", () => {
  it("takes stock and price from the till and keeps barcode/colour/size from the catalog", () => {
    const [row] = mergeSessionItems([v("a")], [item("a")]);
    expect(row).toMatchObject({ id: "a", stock: 4, sellPrice: 10.5, barcode: "Ba", color: "red", size: "M" });
  });

  it("never shows a variant the till does not list (item group / inactive)", () => {
    const out = mergeSessionItems([v("a"), v("b")], [item("a")]);
    expect(out.map((r) => r.id)).toEqual(["a"]);
  });

  it("drops a till item the catalog does not know instead of showing it half blank", () => {
    expect(mergeSessionItems([v("a")], [item("zzz")])).toEqual([]);
  });

  it("uses the till's stock even when the all-warehouse stock is higher", () => {
    const [row] = mergeSessionItems([v("a", { stock: 500 })], [item("a", { available: 0 })]);
    expect(row.stock).toBe(0);
  });

  it("a negative or garbage stock is shown as 0, never as a sellable number", () => {
    expect(mergeSessionItems([v("a")], [item("a", { available: -3 })])[0].stock).toBe(0);
    expect(mergeSessionItems([v("a")], [item("a", { available: "x" })])[0].stock).toBe(0);
  });

  it("tolerates empty inputs", () => {
    expect(mergeSessionItems(undefined, undefined)).toEqual([]);
    expect(mergeSessionItems([v("a")], [])).toEqual([]);
  });
});

describe("fetchAllItems: pages until the server's total is reached", () => {
  const page = (n, total) => ({ items: Array.from({ length: n }, (_, i) => item(`i${i}`)), total });

  it("asks with the server's maximum page size and stops at one page when it is all there is", async () => {
    const f = vi.fn(async () => page(3, 3));
    expect(await fetchAllItems(f)).toHaveLength(3);
    expect(f).toHaveBeenCalledTimes(1);
    expect(f).toHaveBeenCalledWith(0, ITEMS_PAGE);
  });

  it("walks the offsets for a shop bigger than one page", async () => {
    const f = vi.fn(async (offset) => ({ items: Array.from({ length: Math.min(60, 130 - offset) }, (_, i) => item(`${offset + i}`)), total: 130 }));
    const all = await fetchAllItems(f);
    expect(all).toHaveLength(130);
    expect(f.mock.calls.map((c) => c[0])).toEqual([0, 60, 120]);
  });

  it("stops on an empty page even if the total claims more (no endless loop)", async () => {
    const f = vi.fn(async (offset) => (offset === 0 ? page(60, 500) : { items: [], total: 500 }));
    expect(await fetchAllItems(f)).toHaveLength(60);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("fails loudly instead of selling from a list that never ends", async () => {
    const f = vi.fn(async () => page(60, 10 ** 9));
    await expect(fetchAllItems(f)).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(ITEMS_MAX_PAGES);
  });

  it("surfaces a server error rather than returning a partial list", async () => {
    const f = vi.fn(async (offset) => { if (offset) throw new Error("boom"); return page(60, 120); });
    await expect(fetchAllItems(f)).rejects.toThrow("boom");
  });
});

describe("fetchAllProducts: the list has no total, so it stops at the first short page", () => {
  const rows = (n) => Array.from({ length: n }, (_, i) => ({ id: `p${i}` }));
  it("one short page is the whole list", async () => {
    const page = vi.fn().mockResolvedValue(rows(5));
    expect(await fetchAllProducts(page)).toHaveLength(5);
    expect(page).toHaveBeenCalledTimes(1);
    expect(page).toHaveBeenCalledWith(0, PRODUCTS_PAGE);
  });
  it("keeps going while pages are full, and a full last page still ends on the empty one after it", async () => {
    const page = vi.fn().mockResolvedValueOnce(rows(PRODUCTS_PAGE)).mockResolvedValueOnce(rows(PRODUCTS_PAGE)).mockResolvedValueOnce(rows(7));
    expect(await fetchAllProducts(page)).toHaveLength(PRODUCTS_PAGE * 2 + 7);
    expect(page).toHaveBeenNthCalledWith(2, PRODUCTS_PAGE, PRODUCTS_PAGE);
    const exact = vi.fn().mockResolvedValueOnce(rows(PRODUCTS_PAGE)).mockResolvedValueOnce([]);
    expect(await fetchAllProducts(exact)).toHaveLength(PRODUCTS_PAGE);
  });
  it("fails loudly on a list that never ends instead of selling from half of it", async () => {
    const page = vi.fn().mockResolvedValue(rows(PRODUCTS_PAGE));
    await expect(fetchAllProducts(page)).rejects.toThrow(/لا تنتهي/);
    expect(page).toHaveBeenCalledTimes(ITEMS_MAX_PAGES);
  });
});

describe("fetchAllStock / withBarcodes", () => {
  const rows = (n) => Array.from({ length: n }, (_, i) => ({ variant_id: `v${i}`, barcode: `B${i}` }));
  it("stops at the first short page and fails loudly on a list that never ends", async () => {
    const page = vi.fn().mockResolvedValueOnce(rows(STOCK_PAGE)).mockResolvedValueOnce(rows(3));
    expect(await fetchAllStock(page)).toHaveLength(STOCK_PAGE + 3);
    const endless = vi.fn().mockResolvedValue(rows(STOCK_PAGE));
    await expect(fetchAllStock(endless)).rejects.toThrow(/لا تنتهي/);
  });
  it("fills barcodes by variant id and leaves the others alone", () => {
    const out = withBarcodes([{ id: "a", barcode: "" }, { id: "b", barcode: "keep" }], [{ variant_id: "a", barcode: "111" }]);
    expect(out.map((v) => v.barcode)).toEqual(["111", "keep"]);
  });
});
