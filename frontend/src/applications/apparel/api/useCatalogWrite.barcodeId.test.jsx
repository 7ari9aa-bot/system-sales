import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    if (path === "/products/p1") {
      return { id: "p1", title: "تيشيرت", variants: [{ id: "v1", sku: "S1", price: "300.00", option_values: { color: "أسود", size: "M" } }] };
    }
    if (path === "/variants/v1/identifiers" && !opts.method) {
      return [{ id: "ident-9", variant_id: "v1", identifier_type: "barcode", value: "2991000102947" }];
    }
    return { ok: true };
  }),
}));

import { readProductForEdit } from "./useCatalogWrite";

describe("the edit screen's own read keeps each stored barcode's id", () => {
  it("hands the form the id, so a correction can replace that row", async () => {
    const form = await readProductForEdit("p1");
    expect(form.variants[0]).toMatchObject({ barcode: "2991000102947", barcodeId: "ident-9" });
  });
});
