import { describe, expect, it } from "vitest";
import { latinOnly, receiptBytes } from "./receiptPrint";

const receipt = {
  shopName: "محل الأمل",
  items: [{ name: "شاي Lipton", quantity: 1, unit_price: "10", total: "10" }, { name: "سكر", quantity: 2, unit_price: "5", total: "10" }],
  total: "20",
};

describe("receiptBytes", () => {
  it("prints the picture, so Arabic names reach the paper as drawn", () => {
    let seen;
    const out = receiptBytes(receipt, { raster: (r, o) => { seen = [r, o]; return new Uint8Array([1]); }, text: () => { throw new Error("no"); } });
    expect(Array.from(out)).toEqual([1]);
    expect(seen[0]).toBe(receipt);
    expect(seen[1]).toEqual({ paperMm: 80 });
  });

  it("falls back to text, narrowed to what it can print, when there is no canvas", () => {
    let given;
    const out = receiptBytes(receipt, { raster: () => { throw new Error("no canvas"); }, text: (r, o) => { given = [r, o]; return new Uint8Array([2]); } });
    expect(Array.from(out)).toEqual([2]);
    expect(given[0].shopName).toBe("RECEIPT");
    expect(given[0].items.map((i) => i.name)).toEqual(["Lipton", "Item 2"]);
    expect(given[1]).toEqual({ width: 42 });
  });

  it("uses the narrow line width on 58mm paper in both modes", () => {
    let opts;
    receiptBytes(receipt, { paperMm: 58, raster: (_r, o) => { opts = o; return new Uint8Array(); } });
    expect(opts).toEqual({ paperMm: 58 });
    receiptBytes(receipt, { paperMm: 58, raster: () => { throw new Error("x"); }, text: (_r, o) => { opts = o; return new Uint8Array(); } });
    expect(opts).toEqual({ width: 32 });
  });
});

describe("latinOnly", () => {
  it("leaves a Latin receipt untouched", () => {
    const r = { shopName: "Shop", footerNote: "Thanks", items: [{ name: "Tea", quantity: 1 }] };
    expect(latinOnly(r)).toEqual(r);
  });

  it("collapses the gaps an Arabic word leaves and trims the ends", () => {
    expect(latinOnly({ shopName: "A  شاي  B ", items: [] }).shopName).toBe("A B");
  });

  it("numbers an all-Arabic item by its position, starting at 1", () => {
    const out = latinOnly({ shopName: "x", items: [{ name: "شاي" }, { name: "Tea" }, { name: "سكر" }] });
    expect(out.items.map((i) => i.name)).toEqual(["Item 1", "Tea", "Item 3"]);
  });

  it("keeps an absent footer absent and blanks an all-Arabic one", () => {
    expect(latinOnly({ shopName: "x", items: [] }).footerNote).toBeUndefined();
    expect(latinOnly({ shopName: "x", footerNote: "شكراً", items: [] }).footerNote).toBe("");
  });

  it("keeps everything else on the item", () => {
    expect(latinOnly({ shopName: "x", items: [{ name: "شاي", quantity: 3, total: "9" }] }).items[0]).toEqual({ name: "Item 1", quantity: 3, total: "9" });
  });
});
