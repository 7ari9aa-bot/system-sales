import { buildReceiptEscPos } from "./escpos";
import { buildReceiptRaster } from "./escposRaster";
import { currencyLabel, receiptFooterLines, receiptHeaderLines } from "./receiptShop";

/**
 * The bytes to send a thermal printer for one receipt.
 *
 * The picture is the default because it prints Arabic correctly on any printer. Plain text is only
 * the fallback, for a browser with no canvas, and it is Latin-only: text bytes with Arabic names
 * would come out as symbols, so the fallback replaces what it cannot print instead of sending it.
 */
export function receiptBytes(receipt, { paperMm, raster = buildReceiptRaster, text = buildReceiptEscPos } = {}) {
  // The paper is the shop's setting, carried on the receipt. An explicit option still wins, so a
  // printer-setup test can force a width; with neither, the common 80mm roll.
  const mm = paperMm ?? receipt.paperMm ?? 80;
  try {
    return raster(receipt, { paperMm: mm });
  } catch {
    return text(latinOnly(receipt), { width: mm === 58 ? 32 : 42 });
  }
}

const NON_LATIN = /[^\u0020-\u007e]/g;

/** Keep what a Latin code page can print; a name that is all Arabic becomes a plain placeholder. */
export function latinOnly(receipt) {
  const clean = (v, fallback) => {
    const s = String(v ?? "").replace(NON_LATIN, "").replace(/\s+/g, " ").trim();
    return s || fallback;
  };
  return {
    ...receipt,
    shopName: clean(receipt.shopName, "RECEIPT"),
    footerNote: receipt.footerNote ? clean(receipt.footerNote, "") : receipt.footerNote,
    items: (receipt.items ?? []).map((it, n) => ({ ...it, name: clean(it.name, `Item ${n + 1}`) })),
  };
}

/**
 * What the printer draws, from the receipt the screen already holds. The shop's own words, address
 * and exchange period come from ``receipt.shop``, the same block the preview reads, so the paper
 * and the screen say the same thing. ``fallbackName`` is only for a shop that set no name.
 */
export function printableReceipt(receipt, { fallbackName = "" } = {}) {
  const shop = receipt.shop ?? {};
  return {
    shopName: shop.name || fallbackName,
    receiptNumber: receipt.number ?? "",
    items: (receipt.items ?? []).map((it) => ({
      name: it.name,
      quantity: it.qty,
      unit_price: it.price,
      total: it.total,
    })),
    total: receipt.total,
    discount: receipt.discount,
    paperMm: shop.paperMm ?? 80,
    headerLines: receiptHeaderLines(shop),
    footerLines: receiptFooterLines(shop),
    currency: currencyLabel(receipt.currency),
    copies: shop.copies ?? 1,
  };
}
