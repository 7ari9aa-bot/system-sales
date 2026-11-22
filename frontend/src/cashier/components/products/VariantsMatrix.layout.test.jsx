import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import VariantsMatrix from "./VariantsMatrix";

const rows = [
  { id: "row-1", color: "أسود", size: "M", sku: "SKU-0002-0201", barcode: "", sellPrice: 450, stock: 0 },
  { id: "row-2", color: "أسود", size: "L", sku: "SKU-0002-0202", barcode: "", sellPrice: 450, stock: 0 },
];
const wrap = (node) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>);
const html = () => wrap(<VariantsMatrix rows={rows} onChange={() => {}} onGenerate={() => {}} onGenerateBarcodes={() => {}} defaultSell={450} />);

// The 820px-wide table sat inside a ~380px card, so only colour, size and SKU showed and the barcode, price and stock
// (the one thing the user has to type) hid behind a sideways scroll. On a narrow card each combination is a stacked card.
describe("variants list fits a narrow card without sideways scrolling", () => {
  it("each stacked card carries all four labelled fields", () => {
    const h = html();
    const cards = h.split("data-variant-card").slice(1).map((c) => c.slice(0, c.indexOf("</li>")));
    expect(cards).toHaveLength(rows.length);
    for (const card of cards) {
      for (const label of ["SKU", "الباركود", "سعر البيع", "رصيد افتتاحي"]) {
        expect(card).toContain(`>${label}</span>`);
      }
      expect((card.match(/<input/g) ?? []).length).toBe(4);
    }
    expect(h).toContain("SKU-0002-0201");
    expect(h).toContain("SKU-0002-0202");
  });

  it("stacks cards by default and only becomes a table on a wide screen", () => {
    const h = html();
    expect(h).toMatch(/data-variant-card/);
    expect(h).toMatch(/@container/);
    expect(h).toMatch(/@\[860px\]:hidden/);
    expect(h).toMatch(/hidden[^"]*@\[860px\]:block/);
  });

  it("switches on the width of its own card, not the screen (the card is far narrower than the screen)", () => {
    // A screen-width breakpoint (lg:) showed the 820px table inside a ~380px card on a 1150px screen.
    const h = html();
    expect(h).not.toMatch(/\blg:(hidden|block)\b/);
  });

  it("the wide table is not forced wider than its card on a narrow one", () => {
    const h = html();
    const narrow = h.slice(0, h.indexOf("<table"));
    expect(narrow).not.toMatch(/min-w-\[820px\]/);
  });

  it("keeps the saved-row note instead of a stock box", () => {
    const saved = wrap(<VariantsMatrix rows={[{ ...rows[0], id: "abc" }]} onChange={() => {}} onGenerate={() => {}} onGenerateBarcodes={() => {}} defaultSell={450} />);
    expect(saved).toContain("من الجرد");
  });
});
