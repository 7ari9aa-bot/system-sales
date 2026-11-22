import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const state = { value: {} };
vi.mock("@/cashier/api/useCatalogWrite", () => ({ useProductForEdit: () => state.value }));
vi.mock("react-router-dom", async (orig) => ({ ...(await orig()), useParams: () => ({ productId: "p1" }) }));
vi.mock("@/cashier/components/products/ProductEditor", () => ({ default: () => <div>editor-open</div> }));

import ProductEditPage from "./products.$productId.edit.jsx";

const draw = (value, refetch = () => {}) => {
  state.value = { refetch, ...value };
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={["/cashier/products/p1/edit"]}>
      <ProductEditPage />
    </MemoryRouter>,
  );
};

describe("the edit page when the product cannot be loaded", () => {
  it("says the product does not exist only for a 404", () => {
    const html = draw({ isPending: false, isError: true, error: { status: 404 } });
    expect(html).toContain("المنتج غير موجود");
    expect(html).not.toContain("إعادة المحاولة");
  });
  it("never calls a 503 a missing product, and offers a retry", () => {
    const html = draw({ isPending: false, isError: true, error: { status: 503 } });
    expect(html).not.toContain("المنتج غير موجود");
    expect(html).toContain("تعذّر الاتصال بالخادم");
    expect(html).toContain("المنتج موجود ولم يُحذف");
    expect(html).toContain("إعادة المحاولة");
    expect(html).toContain("bg-[#E8761A]");
  });
  it("treats a lost connection like a temporary failure", () => {
    const html = draw({ isPending: false, isError: true, error: { status: 0 } });
    expect(html).not.toContain("المنتج غير موجود");
    expect(html).toContain("إعادة المحاولة");
  });
  it("tells a refused user so, without a retry button", () => {
    const html = draw({ isPending: false, isError: true, error: { status: 403 } });
    expect(html).toContain("غير مسموح");
    expect(html).not.toContain("المنتج غير موجود");
    expect(html).not.toContain("إعادة المحاولة");
  });
  it("opens the editor when the product loaded", () => {
    expect(draw({ isPending: false, isError: false, data: { id: "p1" } })).toContain("editor-open");
  });
  it("wires the retry button to a real reload", () => {
    let reloads = 0;
    const find = (node) => {
      if (!node || typeof node !== "object") return null;
      if (typeof node.props?.onClick === "function") return node.props.onClick;
      const kids = node.props?.children;
      for (const k of Array.isArray(kids) ? kids : [kids]) {
        const hit = find(k);
        if (hit) return hit;
      }
      return null;
    };
    state.value = { refetch: () => { reloads += 1; }, isPending: false, isError: true, error: { status: 503 } };
    const tree = ProductEditPage();
    const onClick = find(tree.props.children[1].props.action);
    expect(typeof onClick).toBe("function");
    onClick();
    expect(reloads).toBe(1);
  });
});
