/**
 * A refused scan, in words the cashier reads. The server answers with a short code (``invalid_barcode``:
 * the number is shaped like a packaged barcode but its check digit does not add up, so it was misread) or
 * an English sentence. Known ones get Arabic; anything else is returned untouched, never hidden.
 */
export function scanRefusalText(refusal, code) {
  if (!refusal) return undefined;
  if (refusal === "invalid_barcode") {
    return `الباركود غلط (${code}). أعد مسح الباركود أو اكتبه بإيدك`;
  }
  if (refusal === "this product is outside this terminal's catalog") {
    return "هذا الصنف خارج الأصناف المتاحة على هذا الكاشير";
  }
  return refusal;
}
