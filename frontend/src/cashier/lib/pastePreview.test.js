import { describe, expect, it } from "vitest";
import { delimiterOf, previewPaste } from "./pastePreview";

const PASTE = [
  "اسم المنتج\tالمقاس\tالسعر\tSKU\tالكمية",
  "تيشيرت قطن\tM\t250\tTEE-M\t4",
  "تيشيرت قطن\tL\t250\tTEE-L\t6",
].join("\n");

describe("previewPaste reads what the merchant copied", () => {
  it("understands Arabic headers copied from Excel, tab separated", () => {
    const out = previewPaste(PASTE);
    expect(out.delimiter).toBe("\t");
    expect(out.columns).toEqual(["title", "size", "price", "sku", "quantity"]);
    expect(out.rows).toHaveLength(2);
    expect(out.productCount).toBe(1);
    expect(out.problems).toEqual([]);
    expect(out.ready).toBe(true);
  });

  it("takes English headers and commas just as well", () => {
    const out = previewPaste("name,price,sku\nShirt,250,S1\n");
    expect(out.rows[0]).toMatchObject({ title: "Shirt", price: "250", sku: "S1" });
  });

  it("refuses a first line it cannot understand, and says which line", () => {
    const out = previewPaste("عمود\tعمود تاني\n1\t2\n");
    expect(out.ready).toBe(false);
    expect(out.problems[0]).toMatchObject({ line: 1 });
    expect(out.problems[0].message).toContain("اسم المنتج");
  });

  it("flags the real problems before anything is uploaded", () => {
    const out = previewPaste(
      ["اسم المنتج,السعر,SKU", "قميص,ألف,SKU-1", ",250,", "قميص,250,SKU-1", "قميص,250,SKU-1"].join("\n"),
    );
    const messages = out.problems.map((p) => p.message).join(" | ");
    expect(messages).toContain("مش رقم");
    expect(messages).toContain("بلا اسم منتج ولا SKU");
    expect(messages).toContain("مكرر");
    expect(out.rows).toHaveLength(3); // الصفوف اللي ليها هوية بس هي اللي بتتعرض
  });

  it("reads 200 pasted rows and keeps every line number", () => {
    const lines = ["اسم المنتج,المقاس,السعر,SKU"];
    for (let i = 0; i < 200; i += 1) lines.push(`منتج ${i},M,100,SKU-${i}`);
    const out = previewPaste(lines.join("\n"));
    expect(out.rows).toHaveLength(200);
    expect(out.rows.at(-1).line).toBe(201);
    expect(out.problems).toEqual([]);
  });

  it("picks the delimiter from the header line, not from a stray comma later", () => {
    expect(delimiterOf("a\tb\n1,2\t3")).toBe("\t");
    expect(delimiterOf("a;b\n1;2")).toBe(";");
  });
});
