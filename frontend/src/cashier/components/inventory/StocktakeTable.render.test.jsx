/**
 * The count sheet has to survive being opened.
 *
 * It shipped with a ReferenceError instead: StocktakeTable builds the scan-save queue with
 * createCountQueue but never imported it, so the whole screen fell into the error boundary and the
 * count sheet listed nothing. Every unit test around it passed because none of them rendered the
 * component. This one does, with the three network hooks stubbed.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/cashier/api/useStocktake", () => ({
  useSaveCounts: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useApproveStocktake: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelStocktake: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/cashier/lib/exportCsv", () => ({ exportCsv: vi.fn() }));
vi.mock("@/cashier/api/useShopOptions", () => ({
  useShopOptions: () => ({ options: { colours: [], sizes: [] } }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import StocktakeTable from "./StocktakeTable";

const SHEET = {
  id: "sheet-1",
  status: "OPEN",
  note: "",
  closedAt: null,
  rows: [
    {
      id: "v-1",
      productName: "ItemA 12345678",
      sku: "LDA-12345678",
      barcode: "630123456781",
      color: "",
      size: "",
      stock: 10,
      startBook: 10,
      countedAt: null,
      actual: 7,
      current: 10,
      drift: 0,
      applied: null,
    },
  ],
};

describe("StocktakeTable", () => {
  it("renders the item and the counts already typed into the sheet", () => {
    const html = renderToStaticMarkup(<StocktakeTable sheet={SHEET} known={[]} />);
    expect(html).toContain("ItemA 12345678");
    // The typed count is what the sheet reconciles against, so it has to be on screen.
    expect(html).toContain('value="7"');
  });
});
