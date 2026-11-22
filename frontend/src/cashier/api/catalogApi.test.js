import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = [];
let failOn = null;
// Default: the deploy has no /products/intake, so the older step chain is what runs (its tests below).
let intakeMissing = true;
// التنفيذ المسجّل للطلبات. باسم، عشان أي اختبار بيستبدله يترجّع في اللي بعده.
async function recordingApi(path, opts = {}) {
    calls.push({ path, method: opts.method ?? "GET", body: opts.body });
    if (failOn && failOn(path, opts)) throw new Error("409 conflict: variant SKU already exists");
    if (path === "/products/intake" && opts.method === "POST") {
      if (intakeMissing) throw Object.assign(new Error("HTTP 404"), { status: 404 });
      return {
        id: "p1",
        title: "تيشيرت قطن",
        slug: "item-t",
        status: "active",
        barcodes_assigned: 1,
        variants: [
          { id: "v1", sku: "TEE-BK-L", barcode: "2000000000015", option_values: { color: "أسود", size: "L" }, price: "150.00" },
          { id: "v2", sku: "TEE-BK-M", barcode: "2000000000022", option_values: { color: "أسود", size: "M" }, price: "150.00" },
        ],
      };
    }
    if (path === "/products" && opts.method === "POST") return { id: "p1", status: "draft", variant_id: null };
    if (/\/products\/p1\/variants$/.test(path)) return { id: `v${calls.filter((c) => /variants$/.test(c.path)).length}` };
    return { ok: true };
  }

vi.mock("@/lib/api", () => ({ api: vi.fn(recordingApi) }));

import { api } from "@/lib/api";

import { catalogApi, countToMovement, isValidEan13, makeSlug, nextSkuBase, validateProduct } from "./catalogApi";

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
  intakeMissing = true;
  // اختبارات التعديل بتبدّل التنفيذ المسجّل؛ من غير الرجوع هنا الاختبارات اللي بعدها مش بتشوف طلبات.
  api.mockImplementation(recordingApi);
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

// The form used to invent a barcode itself (299 + a fixed formula): the first variant of every product got the SAME number,
// the next product collided with it ("already registered") and the product was left half saved. The shop's own barcode is
// now taken from the backend counter, which hands out valid, never-repeated EAN-13 numbers.
describe("createProduct asks the backend for the shop's own barcodes", () => {
  const auto = { ...good, variants: good.variants.map((v) => ({ ...v, barcode: "", autoBarcode: true })) };

  it("never invents a number: no identifier is posted for an auto row, one backend call labels the garment", async () => {
    await catalogApi.createProduct(auto, { warehouseId: "w1", slugToken: "t" });
    expect(calls.filter((c) => /\/identifiers$/.test(c.path))).toHaveLength(0);
    const label = calls.filter((c) => c.path === "/products/p1/barcodes");
    expect(label).toHaveLength(1);
    expect(label[0].method).toBe("POST");
  });

  it("labels only after every variant exists and before the product goes live", async () => {
    await catalogApi.createProduct(auto, { warehouseId: "w1", slugToken: "t" });
    const at = (re) => calls.findIndex((c) => re.test(c.path));
    const lastVariant = calls.map((c) => /variants$/.test(c.path)).lastIndexOf(true);
    expect(at(/\/barcodes$/)).toBeGreaterThan(lastVariant);
    expect(at(/\/barcodes$/)).toBeLessThan(calls.findIndex((c) => c.method === "PATCH" && c.path === "/products/p1"));
  });

  it("does not call the backend when no row asked for an automatic barcode", async () => {
    await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" });
    expect(calls.some((c) => /\/barcodes$/.test(c.path))).toBe(false);
  });

  it("a typed barcode still wins over automatic on the same row", async () => {
    await catalogApi.createProduct({ ...good, variants: [{ ...good.variants[0], autoBarcode: true }] }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.some((c) => /\/identifiers$/.test(c.path))).toBe(true);
    expect(calls.some((c) => /\/barcodes$/.test(c.path))).toBe(false);
  });

  it("a taken barcode is explained in Arabic, with the number and what was already saved", async () => {
    // the exact text the server sent on the real screen
    failOn = (path) => {
      if (!/identifiers$/.test(path)) return false;
      throw new Error("identifier:(SKU-0002-0101 barcode:2991000102947 already registered");
    };
    const err = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch((e) => e);
    expect(err.message).toMatch(/الباركود 2991000102947 مستخدم بالفعل/);
    expect(err.message).toMatch(/تم حفظ: المنتج/);
    expect(err.message).not.toMatch(/already registered/);
  });

  it("a taken SKU is explained in Arabic too", async () => {
    failOn = (path) => /variants$/.test(path);
    const err = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch((e) => e);
    expect(err.message).toMatch(/كود الصنف \(SKU\) مستخدم بالفعل/);
  });
});

describe("createProduct builds a SELLABLE product in the right order", () => {
  it("product -> variants (+barcode, +opening stock) -> activate, with wire-string prices", async () => {
    const r = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" });
    const seq = calls.map((c) => `${c.method} ${c.path}`);
    // أول طلب هو سؤال الـintake (بيرد 404 على النشر القديم)، وبعده السلسلة القديمة زي ما هي.
    expect(seq[0]).toBe("POST /products/intake");
    expect(seq[1]).toBe("POST /products");
    expect(seq).toContain("POST /products/p1/variants");
    expect(seq.at(-1)).toBe("PATCH /products/p1"); // activation is the LAST step
    expect(calls.at(-1).body).toEqual({ status: "active" });
    const variantBodies = calls.filter((c) => /variants$/.test(c.path)).map((c) => c.body);
    expect(variantBodies[0]).toEqual({ sku: "TEE-BK-L", price: "150.00", option_values: { color: "أسود", size: "L" } });
    expect(variantBodies[1].price).toBe("150.00");
    expect(r.product.status).toBe("active");
  });

  it("a season typed on the form goes with the same final PATCH, trimmed", async () => {
    await catalogApi.createProduct({ ...good, season: "  صيف 26 " }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ season: "صيف 26", status: "active" });
  });

  it("no season typed sends none, so a product without one stays without one", async () => {
    await catalogApi.createProduct({ ...good, season: "   " }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ status: "active" });
  });

  it("a material typed on the form goes with the same final PATCH, trimmed", async () => {
    await catalogApi.createProduct({ ...good, material: "  قطن  " }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ material: "قطن", status: "active" });
  });

  it("no material typed sends none, so a product without one stays without one", async () => {
    await catalogApi.createProduct({ ...good, material: "   " }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ status: "active" });
    await catalogApi.createProduct({ ...good, material: null }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ status: "active" });
  });

  it("the text 'null' is never sent as a material", async () => {
    await catalogApi.createProduct({ ...good, material: " null " }, { warehouseId: "w1", slugToken: "t" });
    expect(calls.at(-1).body).toEqual({ status: "active" });
    expect(JSON.stringify(calls)).not.toContain("null\"");
  });

  it("material, season, category and brand all travel on the one activation PATCH", async () => {
    await catalogApi.createProduct(
      { ...good, season: " صيف ", material: " قطن ", categoryId: "c1", brandId: "b1" },
      { warehouseId: "w1", slugToken: "t" },
    );
    expect(calls.at(-1).body).toEqual({ category_id: "c1", brand_id: "b1", season: "صيف", material: "قطن", status: "active" });
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

describe("a shop's own barcode with a wrong check digit is stopped before saving", () => {
  const withBarcode = (barcode) => ({ name: "بنطلون", variants: [{ sku: "A", sellPrice: 650, barcode }] });
  it("knows a valid and an invalid EAN-13", () => {
    expect(isValidEan13("2000000000015")).toBe(true);
    expect(isValidEan13("2991000102947")).toBe(false);
    expect(isValidEan13("200000000001")).toBe(false);
    expect(isValidEan13("abcdefghijklm")).toBe(false);
  });
  it("refuses an in-store code (starts with 2) whose check digit is wrong", () => {
    const e = validateProduct(withBarcode("2991000102947"));
    expect(e).toHaveLength(1);
    expect(e[0]).toContain("غير صحيح");
    expect(e[0]).toContain("2991000102947");
  });
  it("accepts a valid in-store code", () => expect(validateProduct(withBarcode("2000000000015"))).toEqual([]));
  it("leaves a manufacturer or older shop code alone, valid or not", () => {
    expect(validateProduct(withBarcode("6221234567890"))).toEqual([]);
    expect(validateProduct(withBarcode("12345"))).toEqual([]);
    expect(validateProduct(withBarcode("SHOP-77"))).toEqual([]);
  });
});


describe("applyProductEdit: correcting a barcode", () => {
  const plan = (replacesId) => ({
    product: {},
    variantPatches: [],
    newVariants: [],
    newBarcodes: [{ variantId: "v1", value: "2991000102949", ...(replacesId ? { replacesId } : {}) }],
  });
  const idx = (re) => calls.findIndex((c) => re.test(`${c.method} ${c.path}`));

  it("files the right code FIRST, then deletes the wrong one through its own variant", async () => {
    await catalogApi.applyProductEdit("p1", plan("ident-1"));
    const added = idx(/^POST \/variants\/v1\/identifiers$/);
    const removed = idx(/^DELETE \/variants\/v1\/identifiers\/ident-1$/);
    expect(added).toBeGreaterThan(-1);
    expect(removed).toBeGreaterThan(added);
  });
  it("if filing the right code fails, the old one is NOT deleted", async () => {
    failOn = (path, opts) => opts.method === "POST" && /identifiers$/.test(path);
    await expect(catalogApi.applyProductEdit("p1", plan("ident-1"))).rejects.toThrow();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });
  it("a code that replaces nothing deletes nothing", async () => {
    await catalogApi.applyProductEdit("p1", plan(null));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });
});

describe("correcting a wrong barcode end to end (read, edit the form, plan, apply)", () => {
  it("the stored wrong code is deleted and the right one filed, through the real chain", async () => {
    const { api } = await import("@/lib/api");
    const { planProductEdit, productToForm } = await import("./productEdit");
    api.mockImplementation(async (path, opts = {}) => {
      calls.push({ path, method: opts.method ?? "GET", body: opts.body });
      if (path === "/products/p1") {
        return { id: "p1", title: "تيشيرت", variants: [{ id: "v1", sku: "S1", price: "300.00", option_values: { color: "أسود", size: "M" } }] };
      }
      if (path === "/variants/v1/identifiers" && !opts.method) {
        return [{ id: "ident-9", variant_id: "v1", identifier_type: "barcode", value: "2991000102947" }];
      }
      return { ok: true };
    });

    const read = await catalogApi.productForEdit("p1");
    const before = productToForm(read.product, read.barcodes, read.barcodeIds);
    const after = structuredClone(before);
    after.variants[0].barcode = "2991000102949"; // the form row the user retyped
    await catalogApi.applyProductEdit("p1", planProductEdit(before, after));

    const writes = calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.path}`);
    expect(writes).toEqual(["POST /variants/v1/identifiers", "DELETE /variants/v1/identifiers/ident-9"]);
    expect(calls.find((c) => c.method === "POST").body).toEqual({ identifier_type: "barcode", value: "2991000102949" });
  });
});

describe("which stored code the edit screen shows for a variant", () => {
  async function readWith(identifiers) {
    const { api } = await import("@/lib/api");
    api.mockImplementation(async (path) => {
      if (path === "/products/p1") {
        return { id: "p1", title: "تيشيرت", variants: [{ id: "v1", sku: "S1", price: "300.00", option_values: {} }] };
      }
      if (path === "/variants/v1/identifiers") return identifiers;
      return { ok: true };
    });
    return catalogApi.productForEdit("p1");
  }

  it("prefers the shop's own barcode when the variant has several scannable codes", async () => {
    const r = await readWith([
      { id: "i-ean", identifier_type: "ean", value: "6221234567891" },
      { id: "i-bc", identifier_type: "barcode", value: "2991000102949" },
    ]);
    expect(r.barcodes.v1).toBe("2991000102949");
    expect(r.barcodeIds.v1).toBe("i-bc");
  });

  it.each(["ean", "gtin", "upc"])("shows a %s code when the variant has no barcode-type code", async (type) => {
    const r = await readWith([{ id: "i-1", identifier_type: type, value: "6221234567891" }]);
    expect(r.barcodes.v1).toBe("6221234567891");
    expect(r.barcodeIds.v1).toBe("i-1");
  });

  it.each(["external", "qr_token", "egs", "gs1"])("ignores a %s code, which no till scans", async (type) => {
    const r = await readWith([{ id: "i-1", identifier_type: type, value: "ABC-1" }]);
    expect(r.barcodes.v1).toBe("");
    expect(r.barcodeIds.v1).toBe("");
  });
});

// إدخال المنتج كان سلسلة: منتج، ثم طلب لكل تركيبة، وطلب لكل باركود مكتوب، وطلب لكل رصيد افتتاحي،
// وطلب للباركودات المولّدة، وطلب للتفعيل. منتج بـ30 تركيبة = عشرات الطلبات المتتابعة، والبطء كله
// كان في الشبكة. المسار الجديد بيحفظ كل ده في طلب واحد، والسلسلة القديمة بتفضل موجودة كخطة رجوع
// لأي نشر لسه ما عندهوش الـendpoint.
describe("createProduct saves the whole product in ONE request", () => {
  const one = () => {
    intakeMissing = false;
    return catalogApi.createProduct(
      { ...good, season: " صيف 26 ", material: " قطن ", categoryId: "c1", brandId: "b1" },
      { warehouseId: "w1", slugToken: "t" },
    );
  };

  it("sends one request and nothing else", async () => {
    await one();
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].path).toBe("/products/intake");
  });

  it("carries the variants, their typed codes, the opening stock and the auto-barcode wish", async () => {
    intakeMissing = false;
    await catalogApi.createProduct(
      {
        ...good,
        variants: [
          { ...good.variants[0], barcode: "", stock: 7, autoBarcode: true },
          { ...good.variants[1], barcode: "6221234567891", stock: 0 },
        ],
      },
      { warehouseId: "w1", slugToken: "t" },
    );
    const body = calls[0].body;
    expect(body.status).toBe("active");
    expect(body.warehouse_id).toBe("w1");
    expect(body.variants).toEqual([
      { sku: "TEE-BK-L", price: "150.00", option_values: { color: "أسود", size: "L" }, barcode: null, stock: 7, auto_barcode: true },
      { sku: "TEE-BK-M", price: "150.00", option_values: { color: "أسود", size: "M" }, barcode: "6221234567891", stock: 0, auto_barcode: false },
    ]);
  });

  it("carries the classification on the same request, trimmed, and never the text 'null'", async () => {
    await one();
    const body = calls[0].body;
    expect(body.category_id).toBe("c1");
    expect(body.brand_id).toBe("b1");
    expect(body.season).toBe("صيف 26");
    expect(body.material).toBe("قطن");
    expect(JSON.stringify(body)).not.toContain('"null"');
  });

  it("answers in the shape the editor uses, already sellable", async () => {
    const r = await one();
    expect(r.product.id).toBe("p1");
    expect(r.product.status).toBe("active");
    expect(r.variants.map((v) => v.sku)).toEqual(["TEE-BK-L", "TEE-BK-M"]);
    expect(r.variants[0].barcode).toBe("2000000000015");
  });

  it("still refuses opening stock with no warehouse, before asking the server anything", async () => {
    intakeMissing = false;
    await expect(catalogApi.createProduct(good, { slugToken: "t" })).rejects.toThrow(/مخزن/);
    expect(calls).toHaveLength(0);
  });
});

describe("createProduct falls back to the step chain only when the endpoint is missing", () => {
  it("a 404 falls back and the chain still builds a sellable product", async () => {
    intakeMissing = true;
    const r = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" });
    const seq = calls.map((c) => `${c.method} ${c.path}`);
    expect(seq[0]).toBe("POST /products/intake");
    expect(seq).toContain("POST /products");
    expect(seq.at(-1)).toBe("PATCH /products/p1");
    expect(r.product.status).toBe("active");
  });

  it("a real refusal never falls back: it is reported and nothing is created twice", async () => {
    intakeMissing = false;
    failOn = (path) => {
      if (path !== "/products/intake") return false;
      throw Object.assign(new Error("validation_error: السعر لازم يكون أكبر من صفر"), { status: 400 });
    };
    const err = await catalogApi.createProduct(good, { warehouseId: "w1", slugToken: "t" }).catch((e) => e);
    expect(err.status).toBe(400);
    expect(calls.filter((c) => c.path === "/products/intake")).toHaveLength(1);
    expect(calls.some((c) => c.path === "/products")).toBe(false);
  });
});
