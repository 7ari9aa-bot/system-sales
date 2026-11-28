import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ReturnItemsTable from "./ReturnItemsTable";
import ReturnOriginalTable from "./ReturnOriginalTable";

const line = { key: "v1", variantId: "v1", name: "قميص", barcode: "SKU-0001-0101", code: "SKU-0001-0101", qty: 2, maxQty: 2, returnQty: 1, unitNet: 270, total: 540, size: "", color: "", restock: null };
const wrap = (node) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
const totals = { pieces: 1, value: 270 };
const invoice = { detail: { order: { id: "o" }, lines: [] }, number: "POS-1" };

// The column holds the item's SKU (the invoice carries no scan code), so it must not be headed "barcode".
describe("return tables name the code column honestly", () => {
  it("items table", () => {
    const h = wrap(<ReturnItemsTable lines={[line]} totals={totals} onQty={() => {}} onQtyStep={() => {}} onRemove={() => {}} />);
    expect(h).toContain("كود الصنف");
    expect(h).not.toContain(">الباركود<");
    expect(h).toContain("SKU-0001-0101");
  });
  it("original table", () => {
    const h = wrap(<ReturnOriginalTable invoice={invoice} lines={[line]} totals={totals} onStart={() => {}} onQty={() => {}} onQtyStep={() => {}} onCancel={() => {}} onRestock={() => {}} />);
    expect(h).toContain("كود الصنف");
    expect(h).not.toContain(">الباركود<");
  });
});
