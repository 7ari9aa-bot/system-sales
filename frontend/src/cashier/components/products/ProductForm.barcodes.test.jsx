import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import VariantsMatrix from "./VariantsMatrix";
import { readFileSync } from "node:fs";

const wrap = (node) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
const row = (extra = {}) => ({ id: "row-1", color: "أزرق فاتح", size: "M", sku: "SKU-0002-0101", barcode: "", sellPrice: 650, stock: 12, ...extra });
const html = (r) => wrap(<VariantsMatrix rows={[r]} onChange={() => {}} onGenerate={() => {}} onGenerateBarcodes={() => {}} defaultSell={650} />);

// "توليد الباركودات" used to write a number built from a fixed formula in the form: every product's first variant got
// 2991000102947, the second product collided with it and was left half saved. The number now comes from the backend counter
// when the product is saved; the form only marks which rows want one.
// Walk the element tree VariantsMatrix returns (it is a plain function component) and collect every <input> handler.
function barcodeHandlers(rowValue) {
  const calls = [];
  const tree = VariantsMatrix({ rows: [rowValue], onChange: (id, fields) => calls.push({ id, fields }), onGenerate() {}, onGenerateBarcodes() {}, defaultSell: 650 });
  const found = [];
  (function walk(n) {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(walk);
    const p = n.props ?? {};
    if (p.value === rowValue.barcode && typeof p.onChange === "function" && (p.placeholder ?? "").length > 0) found.push(p.onChange);
    walk(p.children);
  })(tree);
  return { found, calls };
}

describe("typing a barcode switches the automatic one off", () => {
  it("both the card input and the wide-table input clear the mark when the user types", () => {
    const { found, calls } = barcodeHandlers(row({ autoBarcode: true }));
    expect(found.length).toBe(2);
    for (const onChange of found) onChange({ target: { value: "2000000000017" } });
    expect(calls).toHaveLength(2);
    for (const c of calls) expect(c.fields).toEqual({ barcode: "2000000000017", autoBarcode: false });
  });
});

describe("the barcode button no longer invents numbers", () => {
  const src = readFileSync(new URL("./ProductForm.jsx", import.meta.url), "utf8");

  it("the form has no barcode formula any more", () => {
    expect(src).not.toMatch(/299\$\{/);
    expect(src).not.toMatch(/7919/);
  });

  it("it marks rows without a barcode and leaves typed ones alone", () => {
    expect(src).toMatch(/autoBarcode: true/);
    expect(src).toMatch(/String\(r\.barcode \?\? ""\)\.trim\(\) \? r :/);
  });

  it("a marked row tells the user the number is made when saving", () => {
    expect(html(row({ autoBarcode: true }))).toContain("يتولّد تلقائيًا عند الحفظ");
  });

  it("an unmarked row keeps the original hint", () => {
    const h = html(row());
    expect(h).toContain("اضغط «توليد الباركودات»");
    expect(h).not.toContain("يتولّد تلقائيًا عند الحفظ");
  });
});
