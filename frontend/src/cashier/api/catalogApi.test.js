import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = [];
let failOn = null;
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    calls.push({ path, method: opts.method ?? "GET", body: opts.body });
    if (failOn && failOn(path, opts)) throw new Error("409 conflict: variant SKU already exists");
    if (path === "/products" && opts.method === "POST") return { id: "p1", status: "draft", variant_id: null };
    if (/\/products\/p1\/variants$/.test(path)) return { id: `v${calls.filter((c) => /variants$/.test(c.path)).length}` };
    return { ok: true };
  }),
}));

import { catalogApi, countToMovement, makeSlug, nextSkuBase, validateProduct } from "./catalogApi";

const good = {
  name: "تيشيرت قطن",
  description: "x",
  variants: [
    { sku: "TEE-BK-L", color: "أسود", size: "L", sellPrice: 150, barcode: "2000001", stock: 5 },
    { sku: "TEE-BK-M", color: "أسود", size: "M", sellPrice: "150.00", barcode: "", stock: 0 },
  ],
};

beforeEach(() => {
  calls.length = 0;
  failOn = null;
});

describe("validateProduct stops an obviously wrong form before any request", () => {
  it("accepts a good form", () => expect(validateProduct(good)).toEqual([]));
  it("needs a name and at least one variant", () => {
    const e = validateProduct({ name: "  ", variants: [] });
    expect(e.join()).toMatch(/اسم المنتج/);
    expect(e.join()).toMatch(/تركيبة واحدة/);
  });
  it("rejects duplicate SKU and duplicate barcode inside one product", () => {
    const e = validateProduct({ name: "a", variants: [{ sku: "X", sellPrice: 1, barcode: "9" }, { sku: "X", sellPrice: 1, barcode: "9" }] });
    expect(e.join()).toMatch(/كود الصنف مكرر/);
    expect(e.join()).toMatch(/الباركود مكرر/);
  });
  it("rejects a missing SKU, a bad price and a fractional or negative quantity", () => {
    expect(validateProduct({ name: "a", variants: [{ sku: "", sellPrice: 1 }] }).join()).toMatch(/SKU/);
    expect(validateProduct({ name: "a", variants: [{ sku: "A", sellPrice: -5 }] }).join()).toMatch(/سعر البيع/);
    expect(validateProduct({ name: "a", variants: [{ sku: "A", sellPrice: 1, stock: 1.5 }] }).join()).toMatch(/الكمية/);
    expect(validateProduct({ name: "a", variants: [{ sku: "A", sellPrice: 1, stock: -1 }] }).join()).toMatch(/الكمية/);
  });
});

describe("makeSlug", () => {
  it("is URL-safe and never empty for an Arabic-only title", () => {
    expect(makeSlug("تيشيرت قطن", "abc")).toBe("item-abc");
    expect(makeSlug("Cotton Tee!!", "abc")).toBe("cotton-tee-abc");
  });
  it("stays within the backend's 255 limit", () => expect(makeSlug("a".repeat(900), "t").length).toBeLessThanOrEqual(255));
});

describe("createProduct builds a SELLABLE product in the right order", () => {
  it("product -> variants (+barcode, +opening stock) -> activate, with wire-string prices", async () => {
    const r = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" });
    const seq = calls.map((c) => `${c.method} ${c.path}`);
    expect(seq[0]).toBe("POST /products");
    expect(seq).toContain("POST /products/p1/variants");
    expect(seq.at(-1)).toBe("PATCH /products/p1"); // activation is the LAST step
    expect(calls.at(-1).body).toEqual({ status: "active" });
    const variantBodies = calls.filter((c) => /variants$/.test(c.path)).map((c) => c.body);
    expect(variantBodies[0]).toEqual({ sku: "TEE-BK-L", price: "150.00", option_values: { color: "أسود", size: "L" } });
    expect(variantBodies[1].price).toBe("150.00");
    expect(r.product.status).toBe("active");
  });

  it("sends the barcode only when present, and stock only when > 0", async () => {
    await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" });
    expect(calls.filter((c) => /identifiers$/.test(c.path))).toHaveLength(1);
    const moves = calls.filter((c) => c.path === "/inventory/movements");
    expect(moves).toHaveLength(1);
    expect(moves[0].body).toMatchObject({ direction: "in", quantity: 5, warehouse_id: "w1", reason: "adjustment" });
  });

  it("refuses opening stock when there is no warehouse (instead of dropping it silently)", async () => {
    await expect(catalogApi.createProduct(good, { slugToken: "t" })).rejects.toThrow(/مخزن/);
  });

  it("never calls the backend when the form is invalid", async () => {
    await expect(catalogApi.createProduct({ name: "", variants: [] })).rejects.toThrow(RangeError);
    expect(calls).toHaveLength(0);
  });

  it("a mid-way failure names the step and what was already saved (no silent half product)", async () => {
    failOn = (path) => /variants$/.test(path);
    const err = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch((e) => e);
    expect(err.message).toMatch(/إضافة التركيبة TEE-BK-L/);
    expect(err.message).toMatch(/تم حفظ: المنتج/);
    expect(err.partial).toEqual(["المنتج"]);
    expect(calls.some((c) => c.method === "PATCH")).toBe(false); // never activated a broken product
  });
});

describe("moveStock follows the probed backend rules", () => {
  const base = { variantId: "v", warehouseId: "w", reason: "adjustment" };
  it("accepts in / out / adjust with a whole quantity >= 1", async () => {
    for (const direction of ["in", "out", "adjust"]) await catalogApi.moveStock({ ...base, direction, quantity: 3 });
    expect(calls).toHaveLength(3);
  });
  it("rejects zero, negative, fractional and unknown directions locally", () => {
    expect(() => catalogApi.moveStock({ ...base, direction: "adjust", quantity: 0 })).toThrow(RangeError);
    expect(() => catalogApi.moveStock({ ...base, direction: "in", quantity: -2 })).toThrow(RangeError);
    expect(() => catalogApi.moveStock({ ...base, direction: "in", quantity: 1.5 })).toThrow(RangeError);
    expect(() => catalogApi.moveStock({ ...base, direction: "hold", quantity: 1 })).toThrow(RangeError);
    expect(calls).toHaveLength(0);
  });
});

describe("countToMovement: one ledger row that makes the system match the shelf", () => {
  const b = { variantId: "v", warehouseId: "w" };
  it("returns null when the count equals the system (no noise)", () => expect(countToMovement({ ...b, onHand: 6, counted: 6 })).toBeNull());
  it("uses adjust to SET the balance when the count differs", () =>
    expect(countToMovement({ ...b, onHand: 6, counted: 4 })).toMatchObject({ direction: "adjust", quantity: 4 }));
  it("works upward too", () => expect(countToMovement({ ...b, onHand: 2, counted: 9 })).toMatchObject({ direction: "adjust", quantity: 9 }));
  it("a counted ZERO becomes an out of everything on hand (adjust 0 is rejected by the backend)", () =>
    expect(countToMovement({ ...b, onHand: 6, counted: 0 })).toMatchObject({ direction: "out", quantity: 6 }));
  it("rejects nonsense counts", () => {
    expect(() => countToMovement({ ...b, onHand: 1, counted: -1 })).toThrow(RangeError);
    expect(() => countToMovement({ ...b, onHand: 1, counted: 1.5 })).toThrow(RangeError);
  });
});

describe("nextSkuBase never reuses a SKU that exists", () => {
  it("starts at SKU-0001 on an empty shop", () => expect(nextSkuBase([])).toBe("SKU-0001"));
  it("goes one past the highest number, ignoring other SKU styles", () =>
    expect(nextSkuBase(["SKU-0101", "SKU-0202", "ADJ-500297", "UI-BELT-D23D", "E2E-EC9D18"])).toBe("SKU-0203"));
  it("is case-insensitive and tolerates null/undefined entries", () => expect(nextSkuBase(["sku-0009", null, undefined])).toBe("SKU-0010"));
  it("two products built one after the other cannot collide", () => {
    const a = nextSkuBase(["SKU-0005"]);
    const b = nextSkuBase(["SKU-0005", `${a}-0101`]);
    expect(a).toBe("SKU-0006");
    expect(b).toBe("SKU-0007");
  });
});

describe("a failed FIRST variant leaves no orphan product behind", () => {
  it("archives the empty product", async () => {
    failOn = (path, opts) => /variants$/.test(path) && opts.method === "POST";
    await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch(() => {});
    expect(calls.some((c) => c.path === "/products/p1/archive" && c.method === "POST")).toBe(true);
  });
  it("does NOT archive when an earlier variant was already saved (keeps the work, reports it)", async () => {
    let n = 0;
    failOn = (path) => /variants$/.test(path) && ++n === 2;
    const err = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch((e) => e);
    expect(err.partial.length).toBeGreaterThan(1);
    expect(calls.some((c) => /archive$/.test(c.path))).toBe(false);
  });
});
