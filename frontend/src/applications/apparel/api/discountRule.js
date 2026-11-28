/**
 * The shop owner sets a discount ceiling on the POS profile; the server refuses a sale above it with
 * an English sentence that carries the owner's number. The cashier reads Arabic, so that one sentence
 * is shown in Arabic with the same number. Any other message is returned untouched, so nothing else
 * is hidden or rewritten by accident.
 */
const CEILING = /this discount is above the (\d+(?:\.\d+)?)% this shop allows/;

export function discountRefusal(message) {
  if (typeof message !== "string") return message;
  const hit = CEILING.exec(message);
  if (!hit) return message;
  return `الخصم أعلى من الحد المسموح في هذا المحل (${hit[1]}%). اطلب موافقة المدير أو قلّل الخصم`;
}
