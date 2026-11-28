import { describe, expect, it } from "vitest";
import { heldFromApi, holdPayload, restoreHeld } from "./heldCarts";
import { posApi } from "./posApi";
import { vi } from "vitest";

const catalog = [
  { id: "v1", sku: "A", productName: "قميص", color: "أحمر", size: "M", stock: 5, sellPrice: 120 },
  { id: "v2", sku: "B", productName: "بنطلون", color: "أزرق", size: "32", stock: 1, sellPrice: 350 },
  { id: "v3", sku: "C", productName: "حزام", color: "", size: "", stock: 0, sellPrice: 80 },
];
const held = (items, extra = {}) => ({ id: "h1", items, label: "أحمد", discount_total: "5.00", created_at: "2026-10-20T10:00:00Z", ...extra });

describe("heldFromApi", () => {
  it("summarises a held cart for the list: label, piece count, time", () => {
    const [h] = heldFromApi([held([{ variant_id: "v1", quantity: 2 }, { variant_id: "v2", quantity: 1 }])], catalog);
    expect(h).toMatchObject({ id: "h1", label: "أحمد", pieces: 3, discount: "5.00" });
    expect(h.lines.map((l) => l.name)).toEqual(["قميص", "بنطلون"]);
  });
  it("unlabelled carts get a stable readable fallback", () => {
    expect(heldFromApi([held([{ variant_id: "v1", quantity: 1 }], { label: null })], catalog)[0].label).toBe("فاتورة معلقة");
  });
  it("oldest first, like the backend orders them", () => {
    const a = held([{ variant_id: "v1", quantity: 1 }], { id: "a", created_at: "2026-10-20T09:00:00Z" });
    const b = held([{ variant_id: "v1", quantity: 1 }], { id: "b", created_at: "2026-10-20T11:00:00Z" });
    expect(heldFromApi([b, a], catalog).map((h) => h.id)).toEqual(["a", "b"]);
  });
});

describe("restoreHeld: prices and stock are re-checked NOW, nothing is trusted from the past", () => {
  it("restores in-stock lines at the current price", () => {
    const r = restoreHeld(held([{ variant_id: "v1", quantity: 2 }]), catalog);
    expect(r.lines).toEqual([expect.objectContaining({ variantId: "v1", qty: 2, price: 120 })]);
    expect(r.dropped).toEqual([]);
  });
  it("a quantity above today's stock is cut to what is left, and reported", () => {
    const r = restoreHeld(held([{ variant_id: "v2", quantity: 3 }]), catalog);
    expect(r.lines[0].qty).toBe(1);
    expect(r.adjusted).toEqual([{ name: "بنطلون", wanted: 3, got: 1 }]);
  });
  it("a sold-out or unknown item is dropped and reported, never silently kept", () => {
    const r = restoreHeld(held([{ variant_id: "v3", quantity: 1 }, { variant_id: "gone", quantity: 1 }, { variant_id: "v1", quantity: 1 }]), catalog);
    expect(r.lines.map((l) => l.variantId)).toEqual(["v1"]);
    expect(r.dropped.map((d) => d.reason)).toEqual(["out_of_stock", "unavailable"]);
  });
  it("if nothing can be restored the cart is flagged so it is not deleted", () => {
    const r = restoreHeld(held([{ variant_id: "v3", quantity: 1 }]), catalog);
    expect(r.lines).toEqual([]);
    expect(r.canRelease).toBe(false);
  });
  it("the saved fixed discount comes back only as a starting value", () => {
    expect(restoreHeld(held([{ variant_id: "v1", quantity: 1 }]), catalog).discount).toBe(5);
  });
  it("duplicate variants in one held cart are merged, then clamped together", () => {
    const r = restoreHeld(held([{ variant_id: "v2", quantity: 1 }, { variant_id: "v2", quantity: 1 }]), catalog);
    expect(r.lines).toHaveLength(1);
    expect(r.lines[0].qty).toBe(1);
  });
});

describe("holdPayload: the screen's cart is converted to the API's item shape", () => {
  const cart = [{ variantId: "v1", qty: 2 }, { variantId: "v2", qty: 1 }];
  it("uses variant_id/quantity", () => {
    expect(holdPayload({ cart, label: "  أحمد " }).items).toEqual([{ variant_id: "v1", quantity: 2 }, { variant_id: "v2", quantity: 1 }]);
  });
  it("trims the label and drops an empty one", () => {
    expect(holdPayload({ cart, label: "  أحمد " }).label).toBe("أحمد");
    expect(holdPayload({ cart, label: "   " }).label).toBeUndefined();
  });
  it("an empty cart cannot be held", () => expect(() => holdPayload({ cart: [] })).toThrow());
  it("the payload is accepted by posApi.holdCart (the exact bug: 'every item needs a variant_id')", async () => {
    const calls = [];
    vi.spyOn(posApi, "holdCart").mockImplementation(async (_id, body) => (calls.push(body), {}));
    await posApi.holdCart("s1", holdPayload({ cart, label: "x" }));
    expect(calls[0].items[0]).toHaveProperty("variant_id", "v1");
  });
});
