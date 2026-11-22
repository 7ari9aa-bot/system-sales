import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

// الأرشفة كانت موجودة في الخادم (POST /products/{id}/archive) ومفيش زرار ليها في أي شاشة،
// فالمسودة الغلط تفضل في الكتالوج للأبد. الزرار دلوقتي في نافذة تفاصيل المنتج ويسأل الأول.

// The dialog is a Radix portal; render its content directly so the markup can be inspected.
vi.mock("@/cashier/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));

import ProductDetailsDialog from "./ProductDetailsDialog";

const draw = (product = { id: "p-7", name: "بنطلون جينز تجربة", variants: [] }) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ProductDetailsDialog product={product} open onOpenChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );

describe("a product can be archived from its own card", () => {
  it("shows the archive button next to the edit button", () => {
    const html = draw();
    expect(html).toContain("أرشفة المنتج");
    expect(html).toContain("تعديل المنتج");
  });

  it("does not ask before the merchant starts: no confirmation on open", () => {
    const html = draw();
    expect(html).not.toContain("أيّوه، أرشفة");
    expect(html).not.toContain("هيختفي من البيع");
  });

  it("the button is a real button in the danger colour, not floating text", () => {
    expect(draw()).toMatch(/<button[^>]*class="[^"]*C6432F[^"]*"[^>]*>(?:(?!<\/button>).)*أرشفة المنتج/s);
  });

  it("offers no archive for a product that has no id", () => {
    expect(draw({ name: "بلا معرّف", variants: [] })).not.toContain("أرشفة المنتج");
  });
});

describe("the archive call is the one the backend already has", () => {
  // The component reads the query cache, so it is inspected as source rather than called as a
  // bare function (hooks need a renderer). The behaviour above is covered by the rendered markup.
  const src = readFileSync(new URL("./ProductDetailsDialog.jsx", import.meta.url), "utf8");

  it("posts to the product's archive path", () => {
    expect(src).toMatch(/catalogApi\.archiveProduct\(product\.id\)/);
  });

  it("refreshes the catalog afterwards, so the archived row leaves the grid", () => {
    expect(src).toMatch(/invalidateQueries\(\{ queryKey: CATALOG_KEY \}\)/);
  });

  it("the visible button only opens the question; the call lives in the confirmed handler", () => {
    expect(src).toMatch(/onClick=\{\(\) => setAsking\(true\)\}/);
    const askAt = src.indexOf("async function archive()");
    const confirmAt = src.indexOf("onClick={archive}");
    expect(askAt).toBeGreaterThan(-1);
    expect(confirmAt).toBeGreaterThan(askAt);
  });

  it("a refusal is shown in Arabic and the dialog stays open", () => {
    expect(src).toMatch(/تعذّرت أرشفة المنتج/);
    expect(src).toMatch(/setError\(e\?\.message/);
  });
});
