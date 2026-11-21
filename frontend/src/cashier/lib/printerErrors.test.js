import { describe, expect, it } from "vitest";
import ar from "@/lib/i18n/ar";
import en from "@/lib/i18n/en";
import { PrinterError, printerErrorKey } from "./printerErrors";

const ASCII_LETTERS = /[A-Za-z]{4,}/;

describe("printer / drawer errors reach the cashier in Arabic", () => {
  it("a known bridge failure maps to its own message key", () => {
    expect(printerErrorKey(new PrinterError("usb_unsupported"), "connectUsb")).toBe("pos.printer.err.usb_unsupported");
    expect(printerErrorKey(new PrinterError("not_connected"), "kick")).toBe("pos.printer.err.not_connected");
  });

  it("raw browser or device text is never shown: it falls back to the action's own message", () => {
    const raw = new Error("NetworkError: Failed to execute 'open' on 'USBDevice': Access denied.");
    expect(printerErrorKey(raw, "connectUsb")).toBe("pos.printer.err.connectUsb");
    expect(printerErrorKey(raw, "kick")).toBe("pos.printer.err.kick");
    expect(printerErrorKey(raw, "testPrint")).toBe("pos.printer.err.testPrint");
    expect(printerErrorKey(raw, "connectBluetooth")).toBe("pos.printer.err.connectBluetooth");
  });

  it("the user closing the device picker is not an error", () => {
    const abort = Object.assign(new Error("No device selected."), { name: "NotFoundError" });
    expect(printerErrorKey(abort, "connectUsb")).toBeNull();
  });

  it("every key it can return exists in Arabic and English, and the Arabic has no English words (product names aside)", () => {
    const keys = [
      "usb_unsupported", "bt_unsupported", "no_characteristic", "not_connected",
      "connectUsb", "connectBluetooth", "testPrint", "kick",
    ].map((k) => `pos.printer.err.${k}`);
    for (const k of keys) {
      expect(ar[k], k).toBeTruthy();
      expect(en[k], k).toBeTruthy();
      expect(ar[k].replace(/WebUSB|WebBluetooth|USB|ESC\/POS|Chrome|Edge/g, ""), k).not.toMatch(ASCII_LETTERS);
    }
  });
});
