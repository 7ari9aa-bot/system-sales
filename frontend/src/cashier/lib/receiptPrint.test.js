import { describe, expect, it } from "vitest";
import { latinOnly, printableReceipt, receiptBytes } from "./receiptPrint";
import { receiptShop } from "./receiptShop";

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

describe("the paper is the shop's setting", () => {
  const seen = () => {
    const got = {};
    return { got, raster: (_r, o) => { got.raster = o; return new Uint8Array(); }, text: (_r, o) => { got.text = o; return new Uint8Array(); } };
  };

  it("a 58mm receipt is drawn for the 58mm roll without anyone passing the width", () => {
    const t = seen();
    receiptBytes({ ...receipt, paperMm: 58 }, { raster: t.raster, text: t.text });
    expect(t.got.raster).toEqual({ paperMm: 58 });
  });

  it("the fallback text uses the narrow line for the same 58mm receipt", () => {
    const t = seen();
    receiptBytes({ ...receipt, paperMm: 58 }, { raster: () => { throw new Error("x"); }, text: t.text });
    expect(t.got.text).toEqual({ width: 32 });
  });

  it("an explicit width still wins, for the printer-setup test", () => {
    const t = seen();
    receiptBytes({ ...receipt, paperMm: 58 }, { paperMm: 80, raster: t.raster, text: t.text });
    expect(t.got.raster).toEqual({ paperMm: 80 });
  });

  it("no setting at all means the common 80mm roll", () => {
    const t = seen();
    receiptBytes(receipt, { raster: t.raster, text: t.text });
    expect(t.got.raster).toEqual({ paperMm: 80 });
  });
});

describe("printableReceipt", () => {
  const held = {
    number: "A-7", total: 372, discount: 15.5, currency: "EGP",
    items: [{ name: "شاي", qty: 2, price: 10, total: 20 }],
    shop: receiptShop({ shop_name: "الأمل", address: "القاهرة", phone: "0100", tax_id: "9", paper_mm: 58, footer_text: "شكراً", copies: 3, exchange_days: 7 }),
  };

  it("draws what the owner set: name, header lines, footer and the exchange promise", () => {
    const out = printableReceipt(held);
    expect(out.shopName).toBe("الأمل");
    expect(out.headerLines).toEqual(["القاهرة", "0100", "الرقم الضريبي: 9"]);
    expect(out.footerLines).toEqual(["شكراً", "الاستبدال خلال 7 يومًا بشرط وجود الفاتورة"]);
    expect(out.paperMm).toBe(58);
    expect(out.copies).toBe(3);
    expect(out.currency).toMatch(/ج\.م/);
  });

  it("carries the items as the receipt holds them", () => {
    expect(printableReceipt(held).items).toEqual([{ name: "شاي", quantity: 2, unit_price: 10, total: 20 }]);
    expect(printableReceipt(held)).toMatchObject({ receiptNumber: "A-7", total: 372, discount: 15.5 });
  });

  it("uses the fallback name only when the owner set none", () => {
    expect(printableReceipt(held, { fallbackName: "x" }).shopName).toBe("الأمل");
    expect(printableReceipt({ ...held, shop: receiptShop({}) }, { fallbackName: "فهرست" }).shopName).toBe("فهرست");
  });

  it("a receipt with no shop block prints plainly: no promise, 80mm, one copy", () => {
    const out = printableReceipt({ ...held, shop: undefined, currency: "" }, { fallbackName: "فهرست" });
    expect(out).toMatchObject({ shopName: "فهرست", paperMm: 80, copies: 1, headerLines: [], footerLines: [], currency: "" });
  });
});
