import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// The dialog is a Radix portal; render its content directly so the markup can be inspected.
vi.mock("@/cashier/components/ui/dialog", () => ({
  Dialog: ({ children }) => <div>{children}</div>,
  DialogContent: ({ children }) => <div>{children}</div>,
  DialogHeader: ({ children }) => <div>{children}</div>,
  DialogTitle: ({ children }) => <h2>{children}</h2>,
  DialogDescription: ({ children }) => <div>{children}</div>,
}));

import ProductDetailsDialog from "./ProductDetailsDialog";

const draw = (product) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ProductDetailsDialog product={product} open onOpenChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );

describe("rendered open, the details dialog shows the way to edit the product", () => {
  it("renders a real link to the edit screen with the visible label, in orange", () => {
    const html = draw({ id: "p-7", name: "تيشيرت", variants: [] });
    expect(html).toContain('href="/cashier/products/p-7/edit"');
    expect(html).toContain("تعديل المنتج");
    expect(html).toContain("bg-[#E8761A]");
  });
  it("renders no edit link for a product that has no id", () => {
    expect(draw({ name: "بلا معرّف", variants: [] })).not.toContain("تعديل المنتج");
  });
});
