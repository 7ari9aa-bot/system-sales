/**
 * What the till says when the paper did not come out.
 *
 * The sale is already saved by the time anything is printed, so a printer failure must never look
 * like a sale that failed and must never be silent: the cashier is told the invoice is safe, given
 * the reason when it is one the bridge knows, and handed the reprint. Raw browser/hardware text is
 * never shown - it is English from the device and means nothing on the shop floor.
 */
import { PrinterError } from "./printerErrors";

const REASONS = {
  usb_unsupported: "المتصفح ده مش بيدعم الطباعة عبر USB.",
  bt_unsupported: "المتصفح ده مش بيدعم الطباعة عبر البلوتوث.",
  no_characteristic: "الطابعة مش بتستقبل أوامر الطباعة.",
  not_connected: "الطابعة مش موصولة.",
};

// Closing the browser's device picker is a decision, not a failure: say nothing about it.
const CANCELLED = new Set(["NotFoundError", "AbortError"]);

/**
 * The warning to show after a print attempt, or null when there is nothing worth saying.
 * `receiptNumber` is the saved invoice's number, so the cashier knows which paper is missing.
 */
export function printFailureNotice(err, { receiptNumber = "" } = {}) {
  if (err && CANCELLED.has(err.name)) return null;
  const reason = err instanceof PrinterError ? REASONS[err.code] ?? "" : "";
  const number = String(receiptNumber ?? "").trim();
  const saved = number ? `تم حفظ الفاتورة ${number}` : "تم حفظ الفاتورة";
  return {
    message: `${saved}، لكن الطباعة لم تكتمل.${reason ? ` ${reason}` : ""} اضغط «إعادة الطباعة» لطبع نسخة.`,
    actionLabel: "إعادة الطباعة",
  };
}

/** The drawer is a second device on the same printer: it can fail while the paper printed fine. */
export function drawerFailureNotice() {
  return {
    message: "الفاتورة اتحفظت، لكن درج النقدية لم يُفتح. افتحه يدويًا أو راجع اتصال الطابعة.",
    actionLabel: null,
  };
}
