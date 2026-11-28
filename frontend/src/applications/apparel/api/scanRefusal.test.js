import { describe, expect, it } from "vitest";
import { scanRefusalText } from "./scanRefusal";

describe("scanRefusalText: what the cashier reads when a scan is refused", () => {
  it("says the barcode is wrong, and tells the cashier what to do", () => {
    const msg = scanRefusalText("invalid_barcode", "6221234567890");
    expect(msg).toContain("6221234567890");
    expect(msg).toMatch(/الباركود غلط/);
    expect(msg).toMatch(/أعد/);
  });
  it("says a product from another section is outside this till, not that it was not found", () => {
    expect(scanRefusalText("this product is outside this terminal's catalog", "123")).toMatch(/خارج/);
  });
  it("never hides a message it does not know: it is shown as the server sent it", () => {
    expect(scanRefusalText("product is archived", "123")).toBe("product is archived");
  });
  it("returns nothing when there was no refusal", () => {
    expect(scanRefusalText(undefined, "123")).toBeUndefined();
    expect(scanRefusalText("", "123")).toBeUndefined();
  });
});
