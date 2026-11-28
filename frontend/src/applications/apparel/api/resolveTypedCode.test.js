import { describe, expect, it } from "vitest";
import { resolveTypedCode } from "./catalogAdapter";

const v = (id, barcode, stock = 5, sku = `SKU-${id}`) => ({ id, productName: `صنف ${id}`, sku, barcode, color: "", size: "", stock });

describe("resolveTypedCode (what the till does when the backend scan did not answer)", () => {
  it("an exact barcode wins over a longer code that merely contains it", () => {
    const r = resolveTypedCode([v("a", "1234"), v("b", "99912345")], "1234");
    expect(r).toMatchObject({ kind: "one", variant: { id: "a" } });
  });
  it("an exact SKU is found when no barcode matches", () => {
    const r = resolveTypedCode([v("a", "111"), v("b", "222")], "sku-b");
    expect(r).toMatchObject({ kind: "one", variant: { id: "b" } });
  });
  it("separators and case do not matter", () => {
    expect(resolveTypedCode([v("a", "R-002999")], "r002999")).toMatchObject({ kind: "one" });
  });
  it("a sold-out item says sold out, not 'not found'", () => {
    const r = resolveTypedCode([v("a", "6221234567890", 0)], "6221234567890");
    expect(r).toMatchObject({ kind: "soldout", variant: { id: "a" } });
  });
  it("two in-stock items on the same exact code are ambiguous", () => {
    expect(resolveTypedCode([v("a", "555"), v("b", "555")], "555").kind).toBe("many");
  });
  it("falls back to a partial name search when no code matches exactly", () => {
    const r = resolveTypedCode([{ ...v("a", "1"), productName: "قميص أحمر" }, v("b", "2")], "احمر");
    expect(r).toMatchObject({ kind: "one", variant: { id: "a" } });
  });
  it("unknown or empty is none", () => {
    expect(resolveTypedCode([v("a", "1")], "zzz").kind).toBe("none");
    expect(resolveTypedCode([v("a", "1")], "  ").kind).toBe("none");
  });
});
