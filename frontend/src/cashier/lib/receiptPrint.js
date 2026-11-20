import { buildReceiptEscPos } from "./escpos";
import { buildReceiptRaster } from "./escposRaster";

/**
 * The bytes to send a thermal printer for one receipt.
 *
 * The picture is the default because it prints Arabic correctly on any printer. Plain text is only
 * the fallback, for a browser with no canvas, and it is Latin-only: text bytes with Arabic names
 * would come out as symbols, so the fallback replaces what it cannot print instead of sending it.
 */
export function receiptBytes(receipt, { paperMm = 80, raster = buildReceiptRaster, text = buildReceiptEscPos } = {}) {
  try {
    return raster(receipt, { paperMm });
  } catch {
    return text(latinOnly(receipt), { width: paperMm === 58 ? 32 : 42 });
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
