import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import InventoryGridSkeleton from "./InventoryGridSkeleton";

describe("the stock grid while it loads", () => {
  const html = renderToStaticMarkup(<InventoryGridSkeleton count={4} />);

  it("shows card skeletons instead of a bare loading line", () => {
    expect(html).toContain('data-testid="inventory-grid-loading"');
    expect(html).toContain("animate-pulse");
  });

  it("keeps the bare loading sentence out of the visible text", () => {
    expect(html).not.toContain("جاري تحميل المخزون…</p>");
  });

  it("announces the wait once and stays decorative", () => {
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('aria-hidden="true"');
  });
});
