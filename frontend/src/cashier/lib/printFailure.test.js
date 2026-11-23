import { describe, expect, it } from "vitest";
import { PrinterError } from "./printerErrors";
import { drawerFailureNotice, printFailureNotice } from "./printFailure";

describe("printFailureNotice", () => {
  it("tells the cashier the invoice is saved and names the invoice number", () => {
    const notice = printFailureNotice(new PrinterError("not_connected"), { receiptNumber: "INV-42" });
    expect(notice.message).toContain("تم حفظ الفاتورة INV-42");
    expect(notice.message).toContain("الطباعة لم تكتمل");
    expect(notice.actionLabel).toBe("إعادة الطباعة");
  });

  it("names the reason when the bridge knows it", () => {
    const notice = printFailureNotice(new PrinterError("no_characteristic"), { receiptNumber: "7" });
    expect(notice.message).toContain("مش بتستقبل أوامر الطباعة");
  });

  it("still warns without a reason for a raw hardware or browser error", () => {
    const err = new Error("NetworkError: transferOut failed");
    const notice = printFailureNotice(err, { receiptNumber: "7" });
    expect(notice).not.toBeNull();
    expect(notice.message).toContain("تم حفظ الفاتورة 7");
    // The device's English never reaches the shop floor.
    expect(notice.message).not.toContain("NetworkError");
  });

  it("says nothing when the cashier closed the device picker", () => {
    expect(printFailureNotice(Object.assign(new Error("cancelled"), { name: "NotFoundError" }))).toBeNull();
    expect(printFailureNotice(Object.assign(new Error("cancelled"), { name: "AbortError" }))).toBeNull();
  });

  it("works without a receipt number", () => {
    const notice = printFailureNotice(new PrinterError("not_connected"));
    expect(notice.message.startsWith("تم حفظ الفاتورة،")).toBe(true);
  });
});

describe("drawerFailureNotice", () => {
  it("separates the drawer from the paper and offers no reprint", () => {
    const notice = drawerFailureNotice();
    expect(notice.message).toContain("درج النقدية");
    expect(notice.actionLabel).toBeNull();
  });
});
