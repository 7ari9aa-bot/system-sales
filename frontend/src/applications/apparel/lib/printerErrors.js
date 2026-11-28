/**
 * Printer and cash-drawer failures, told to the cashier in the shop's language.
 *
 * The bridge throws a `PrinterError` with a short code for the failures it knows. Anything else
 * (a WebUSB / WebBluetooth / device message) is raw English from the browser or the hardware, so it
 * is never shown: the screen falls back to a message for the action that was being tried.
 */
export class PrinterError extends Error {
  constructor(code) {
    super(code);
    this.name = "PrinterError";
    this.code = code;
  }
}

const KNOWN = new Set(["usb_unsupported", "bt_unsupported", "no_characteristic", "not_connected"]);

/** The translation key to show for `err`, or null when the cashier just closed the device picker. */
export function printerErrorKey(err, action) {
  if (err?.name === "NotFoundError" || err?.name === "AbortError") return null;
  if (err instanceof PrinterError && KNOWN.has(err.code)) return `pos.printer.err.${err.code}`;
  return `pos.printer.err.${action}`;
}
