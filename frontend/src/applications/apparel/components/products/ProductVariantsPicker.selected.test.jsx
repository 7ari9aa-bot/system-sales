import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CHIP_ON } from "./formStyles";
import ProductVariantsPicker from "./ProductVariantsPicker";

const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

const props = { colors: ["أسود"], sizes: ["M"], presetSizes: ["S", "M", "L"], canGenerate: true, onToggleColor: () => {}, onToggleSize: () => {}, onGenerate: () => {} };
const html = () => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><ProductVariantsPicker {...props} /></QueryClientProvider>);

// A picked colour or size was nearly invisible (background contrast 1.05 against an unpicked one).
describe("a picked colour or size is clearly different from an unpicked one", () => {
  it("the selected background stands out from the idle field background", () => {
    const bg = CHIP_ON.match(/bg-\[(#[0-9a-f]{6})\]/i)[1];
    expect(ratio(bg, "#faf9f7")).toBeGreaterThan(1.2);
  });
  it("the selected chip has a ring and the label stays readable on it", () => {
    expect(CHIP_ON).toContain("ring-2");
    const bg = CHIP_ON.match(/bg-\[(#[0-9a-f]{6})\]/i)[1];
    expect(ratio("#3a342d", bg)).toBeGreaterThan(7);
  });
  it("tells assistive tech which chips are on", () => {
    const h = html();
    expect(h.match(/aria-pressed="true"/g)?.length).toBe(2); // one colour, one size
    expect(h.match(/aria-pressed="false"/g)?.length).toBeGreaterThan(5);
  });
});
