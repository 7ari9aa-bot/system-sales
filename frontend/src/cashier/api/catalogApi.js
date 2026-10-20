/**
 * Catalog WRITE client: products, variants, barcodes, price, opening stock, status.
 * (Reads already live in posApi.products / posApi.stockBalances.)
 *
 * Backend facts this file is built on (probed against the real API, not guessed):
 *  - POST /products makes a DRAFT with NO variants. A draft is invisible to the POS (it only
 *    sells status === "active"), so createProduct() ends by activating it.
 *  - Every colour/size is its own variant: POST /products/{id}/variants { price, sku, option_values }.
 *  - SKU, barcode and slug are unique. A duplicate answers 409 with a readable message.
 *  - Stock enters by a ledger movement (direction "in"), never by editing a number.
 *  - Archiving does NOT remove the product from GET /products: callers must filter by status.
 *
 * MONEY goes through toWire(); a bad value throws BEFORE any request is made.
 */
import { api } from "@/lib/api";
import { toWire } from "./money";

const seg = (v) => encodeURIComponent(String(v));
const post = (path, body) => api(path, { method: "POST", body });
const patch = (path, body) => api(path, { method: "PATCH", body });

/** URL-safe, unique slug. Arabic titles have no ASCII letters, so we fall back to a token. */
export function makeSlug(title, token = Date.now().toString(36)) {
  const ascii = String(title ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return `${ascii || "item"}-${token}`.slice(0, 255);
}

/**
 * Next free SKU base, "SKU-0001" style, from the SKUs that already exist.
 * (The editor used Math.random, which collides: the backend answers 409 on a duplicate SKU.)
 * Pass the product's colour/size index to get "SKU-0007-0102".
 */
export function nextSkuBase(existingSkus = []) {
  const used = existingSkus
    .map((s) => /^SKU-(\d+)/.exec(String(s ?? "").toUpperCase()))
    .filter(Boolean)
    .map((m) => Number(m[1]));
  const next = (used.length ? Math.max(...used) : 0) + 1;
  return `SKU-${String(next).padStart(4, "0")}`;
}

/** Validate the editor payload locally so an obviously wrong form never reaches the server. */
export function validateProduct(input) {
  const errors = [];
  if (!String(input?.name ?? "").trim()) errors.push("اسم المنتج مطلوب");
  const variants = input?.variants ?? [];
  if (variants.length === 0) errors.push("أضف تركيبة واحدة على الأقل (لون/مقاس)");
  const seenSku = new Set();
  const seenBarcode = new Set();
  variants.forEach((v, i) => {
    const n = i + 1;
    const sku = String(v.sku ?? "").trim();
    if (!sku) errors.push(`التركيبة ${n}: كود الصنف (SKU) مطلوب`);
    else if (seenSku.has(sku)) errors.push(`التركيبة ${n}: كود الصنف مكرر داخل نفس المنتج`);
    seenSku.add(sku);
    const bc = String(v.barcode ?? "").trim();
    if (bc) {
      if (seenBarcode.has(bc)) errors.push(`التركيبة ${n}: الباركود مكرر داخل نفس المنتج`);
      seenBarcode.add(bc);
    }
    try {
      toWire(v.sellPrice);
    } catch {
      errors.push(`التركيبة ${n}: سعر البيع غير صالح`);
    }
    const stock = Number(v.stock ?? 0);
    if (!Number.isInteger(stock) || stock < 0) errors.push(`التركيبة ${n}: الكمية لازم عدد صحيح 0 أو أكثر`);
  });
  return errors;
}

function optionValues(v) {
  const o = {};
  if (String(v.color ?? "").trim()) o.color = String(v.color).trim();
  if (String(v.size ?? "").trim()) o.size = String(v.size).trim();
  return o;
}

export const catalogApi = {
  warehouses: () => api("/warehouses"),
  ensureDefaultWarehouse: () => post("/warehouses/ensure-default", {}),
  categories: () => api("/categories"),
  brands: () => api("/brands"),
  createCategory: (name) => post("/categories", { name }),
  createBrand: (name) => post("/brands", { name }),

  /**
   * Create a complete, SELLABLE product. Steps run in order; if one fails the error says which
   * step and what already exists, so nothing is silently half-saved.
   */
  async createProduct(input, { warehouseId, slugToken } = {}) {
    const errors = validateProduct(input);
    if (errors.length) throw new RangeError(errors.join(" • "));

    const created = [];
    const step = async (name, fn) => {
      try {
        return await fn();
      } catch (e) {
        const err = new Error(`تعذّر ${name}${created.length ? ` (تم حفظ: ${created.join("، ")})` : ""}: ${e?.message ?? e}`);
        err.cause = e;
        err.partial = [...created];
        throw err;
      }
    };

    // A product with zero variants is an orphan (a draft nobody can sell). If the FIRST variant fails,
    // archive it so the failed attempt leaves nothing behind. Later failures keep what was saved and say so.
    const cleanupIfEmpty = async (productId, savedVariants) => {
      if (savedVariants === 0) await post(`/products/${seg(productId)}/archive`, {}).catch(() => {});
    };

    const product = await step("إنشاء المنتج", () =>
      post("/products", { title: String(input.name).trim(), slug: makeSlug(input.name, slugToken), description: input.description || null }),
    );
    created.push("المنتج");

    const out = [];
    for (const v of input.variants) {
      let variant;
      try {
        variant = await step(`إضافة التركيبة ${v.sku}`, () =>
          post(`/products/${seg(product.id)}/variants`, { sku: String(v.sku).trim(), price: toWire(v.sellPrice), option_values: optionValues(v) }),
        );
      } catch (e) {
        await cleanupIfEmpty(product.id, out.length);
        throw e;
      }
      created.push(v.sku);
      if (String(v.barcode ?? "").trim()) {
        await step(`حفظ باركود ${v.sku}`, () =>
          post(`/variants/${seg(variant.id)}/identifiers`, { identifier_type: "barcode", value: String(v.barcode).trim() }),
        );
      }
      const qty = Number(v.stock ?? 0);
      if (qty > 0) {
        if (!warehouseId) throw new Error("لا يوجد مخزن افتراضي لاستلام الكمية الافتتاحية");
        await step(`إدخال كمية ${v.sku}`, () =>
          post("/inventory/movements", { variant_id: variant.id, warehouse_id: warehouseId, direction: "in", quantity: qty, reason: "adjustment" }),
        );
      }
      out.push(variant);
    }

    await step("تفعيل المنتج", () => patch(`/products/${seg(product.id)}`, { status: "active" }));
    return { product: { ...product, status: "active" }, variants: out };
  },

  updateProduct: (id, fields) => patch(`/products/${seg(id)}`, fields),
  setVariantPrice: (variantId, price) => patch(`/variants/${seg(variantId)}`, { price: toWire(price) }),
  setVariantActive: (variantId, isActive) => patch(`/variants/${seg(variantId)}`, { is_active: !!isActive }),
  archiveProduct: (id) => post(`/products/${seg(id)}/archive`, {}),
  resolveBarcode: (value) => api(`/identifiers/barcode/${seg(value)}`),

  /** Stock IN/OUT/ADJUST as a ledger row. quantity is a positive integer; "adjust" SETS the balance to it. */
  moveStock: ({ variantId, warehouseId, direction, quantity, reason }) => {
    if (!["in", "out", "adjust"].includes(direction)) throw new RangeError(`catalogApi: bad direction "${direction}"`);
    // The backend rejects quantity <= 0 for EVERY direction (422), "adjust" included. "adjust" means
    // "set the balance TO this number" (probed: adjust 7 -> on_hand 7), so a counted ZERO cannot be
    // recorded with it: use an "out" for the whole remaining quantity instead (see countToMovement).
    if (!Number.isInteger(quantity) || quantity < 1) throw new RangeError("catalogApi: quantity must be a whole number >= 1");
    return post("/inventory/movements", { variant_id: variantId, warehouse_id: warehouseId, direction, quantity, reason });
  },
  movements: () => api("/inventory/movements?limit=500"),
};

/**
 * Turn a physical count into the one ledger row that makes the system match it.
 * Probed rules: "adjust" sets the balance to quantity, but quantity must be >= 1, so a counted 0
 * becomes an "out" of everything on hand. Returns null when nothing differs (no row, no noise).
 */
export function countToMovement({ variantId, warehouseId, onHand, counted, reason = "adjustment" }) {
  if (!Number.isInteger(counted) || counted < 0) throw new RangeError("countToMovement: counted must be a whole number >= 0");
  if (!Number.isInteger(onHand) || onHand < 0) throw new RangeError("countToMovement: onHand must be a whole number >= 0");
  if (counted === onHand) return null;
  if (counted === 0) return { variantId, warehouseId, direction: "out", quantity: onHand, reason };
  return { variantId, warehouseId, direction: "adjust", quantity: counted, reason };
}
