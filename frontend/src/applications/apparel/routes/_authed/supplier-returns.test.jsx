import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = { working: { status: "open", session: { id: "sess-1" } } };

vi.mock("@/applications/apparel/api/usePurchasing", () => ({
  useSuppliers: () => ({ data: [{ id: "sup-1", name: "مورد القاهرة" }] }),
  usePurchaseOrders: () => ({ data: [{ id: "po-1", number: "PO-1" }] }),
  useSupplierReturns: () => ({
    data: [
      {
        id: "ret-1",
        number: "SR-1",
        date: "2026-11-20",
        supplierId: "sup-1",
        supplierName: "مورد القاهرة",
        poNumber: "PO-1",
        settlement: "cash",
        status: "pending",
        amount: "150.00",
        qty: 2,
        items: [{ variantId: "v1", name: "قميص", qty: 2, price: "75.00" }],
      },
    ],
  }),
  useCreateSupplierReturn: () => ({ mutate: vi.fn(), isPending: false }),
  useAcceptSupplierReturn: () => ({ mutate: vi.fn(), isPending: false, variables: null, error: null }),
  useRejectSupplierReturn: () => ({ mutate: vi.fn(), isPending: false, variables: null, error: null }),
}));
vi.mock("@/applications/apparel/api/usePosSale", () => ({
  useCatalog: () => ({ data: [{ id: "v1", name: "قميص", sku: "SKU-1" }] }),
}));
vi.mock("@/applications/apparel/api/useShifts", () => ({
  useWorkingSession: () => ({ data: state.working }),
}));

import SupplierReturnsPage from "./supplier-returns.jsx";

const draw = () =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={["/cashier/supplier-returns"]}>
      <SupplierReturnsPage />
    </MemoryRouter>,
  );

describe("the supplier returns page", () => {
  beforeEach(() => {
    state.working = { status: "open", session: { id: "sess-1" } };
  });

  it("mounts with the open shift it needs for a cash settlement", () => {
    // The page read useWorkingSession() and buildReturnAcceptance() without importing them, so it
    // threw before rendering anything at all.
    const html = draw();
    expect(html).toContain("مرتجعات الموردين");
    expect(html).toContain("SR-1");
    expect(html).toContain("مورد القاهرة");
  });

  it("still renders when no shift is open, so the drawer is not the only path", () => {
    state.working = { status: "closed", session: null };
    const html = draw();
    expect(html).toContain("مرتجعات الموردين");
  });
});
