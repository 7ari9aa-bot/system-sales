import { describe, expect, it } from "vitest";
import { receiptHeader } from "./shopProfile";

describe("receiptHeader", () => {
  it("uses the real shop name", () => expect(receiptHeader({ name: "  E2E Shop " }).name).toBe("E2E Shop"));
  it("never prints a tax number, phone or branch nobody entered", () => {
    expect(receiptHeader({ name: "X" })).toEqual({ name: "X", branch: "", phone: "", taxId: "" });
  });
  it("prints them when they really exist", () => {
    expect(receiptHeader({ name: "X" }, { taxId: "123-456", phone: "01000000000" })).toMatchObject({ taxId: "123-456", phone: "01000000000" });
  });
  it("falls back to a neutral name, never to another shop's", () => {
    expect(receiptHeader(null).name).toBe("المتجر");
    expect(receiptHeader({ name: "   " }).name).toBe("المتجر");
  });
});
