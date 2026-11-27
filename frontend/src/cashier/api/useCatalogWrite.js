import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { catalogApi } from "./catalogApi";
import { CATALOG_KEY } from "./usePosSale";
import { planProductEdit, productToForm, shouldRetryEditLoad } from "./productEdit";
import { planOpeningDistribution } from "@/cashier/lib/stockDistribution";

/** كل مخازن المحل النشطة: الاختيار في نموذج المنتج بيتبني عليها، والأول النشط هو الافتراضي. */
export function useWarehouses() {
  return useQuery({
    queryKey: ["cashier", "warehouses"],
    staleTime: 60_000,
    queryFn: async () => {
      const list = await catalogApi.warehouses().catch(() => []);
      return Array.isArray(list) ? list : (list?.items ?? []);
    },
  });
}

/** The default warehouse id, created on first use (a brand-new shop has none). */
export async function defaultWarehouseId() {
  const list = await catalogApi.warehouses();
  const rows = Array.isArray(list) ? list : (list?.items ?? []);
  const active = rows.find((w) => w.is_active) ?? rows[0];
  if (active) return active.id;
  const made = await catalogApi.ensureDefaultWarehouse();
  return made?.id ?? null;
}

/** Save a product to the backend, then refresh the POS catalog so it is sellable right away. */
/**
 * يحفظ منتج جديد ويوزّع رصيده الافتتاحي على المخازن المختارة.
 * الرصيد في النموذج إجمالي؛ الـintake بياخد نصيب المخزن الأساسي، وبعد كده كل مخزن تاني
 * بياخد حركة «in» بكميته. فشل حركة توزيع ما بيلغيش المنتج — بيتقال بالاسم في النتيجة.
 */
export async function saveProductWithDistribution(input, warehouseId) {
  const plan = planOpeningDistribution(input.variants ?? [], input.warehouses ?? [], warehouseId);
  const variants = (input.variants ?? []).map((v) => ({
    ...v,
    stock: plan.primaryStock[v.id ?? v.sku] ?? Number(v.stock ?? 0),
  }));
  const created = await catalogApi.createProduct({ ...input, variants }, { warehouseId });

  const bySku = new Map((created?.variants ?? []).map((v) => [String(v.sku ?? "").trim(), v.id]));
  const failed = [];
  for (const move of plan.movements) {
    const variantId = bySku.get(String(move.sku ?? "").trim());
    if (!variantId) {
      failed.push({ ...move, message: "التركيبة غير موجودة بعد الحفظ" });
      continue;
    }
    try {
      await catalogApi.moveStock({ variantId, warehouseId: move.warehouseId, direction: "in", quantity: move.quantity, reason: "adjustment" });
    } catch (e) {
      failed.push({ ...move, message: e?.message ?? String(e) });
    }
  }
  return { ...created, distribution: { planned: plan.movements, failed } };
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const needsStock = (input.variants ?? []).some((v) => Number(v.stock) > 0);
      // المخزن اللي اختاره التاجر بيفوز؛ لو مفيش اختيار (أو مفيش رصيد) بنرجع للمخزن الافتراضي.
      const warehouseId = needsStock ? input.warehouseId || (await defaultWarehouseId()) : undefined;
      return saveProductWithDistribution(input, warehouseId);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: CATALOG_KEY }),
  });
}

/**
 * The next SKU base, straight from the server (one aggregate query).
 * `null` means this deploy has no /products/next-sku yet, so the screen falls back to counting
 * the catalog it already loads — see useExistingSkus below, kept for exactly that case.
 */
export function useNextSkuBase() {
  return useQuery({
    queryKey: [...CATALOG_KEY, "next-sku"],
    staleTime: 0,
    queryFn: async () => {
      try {
        const res = await catalogApi.nextSku();
        return res?.base ?? null;
      } catch (e) {
        if (e?.status !== 404) throw e;
        return null;
      }
    },
  });
}

/** Every SKU that exists in the backend now (used to pick a free SKU base). Includes archived products. */
export function useExistingSkus(enabled = true) {
  return useQuery({
    queryKey: [...CATALOG_KEY, "skus"],
    staleTime: 0,
    enabled,
    queryFn: async () => {
      const res = await posApi.products();
      const list = Array.isArray(res) ? res : (res?.items ?? []);
      return list.flatMap((p) => (p.variants ?? []).map((v) => v.sku).filter(Boolean));
    },
  });
}

/** Real categories and brands of this shop (id + name). A new shop has none, so the form offers "add new". */
export function useCategories() {
  return useQuery({
    queryKey: ["cashier", "catalog", "categories"],
    queryFn: async () => ((await catalogApi.categories()) ?? []).map((c) => ({ id: c.id, name: c.name })),
  });
}

export function useBrands() {
  return useQuery({
    queryKey: ["cashier", "catalog", "brands"],
    queryFn: async () => ((await catalogApi.brands()) ?? []).map((b) => ({ id: b.id, name: b.name })),
  });
}

/** Create a category / brand from the product form so a brand-new shop is never stuck with an empty list. */
export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => catalogApi.createCategory(String(name).trim()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cashier", "catalog", "categories"] }),
  });
}

export function useCreateBrand() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => catalogApi.createBrand(String(name).trim()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cashier", "catalog", "brands"] }),
  });
}

/**
 * The read the edit screen runs: a product with each variant's stored barcode, that barcode's id,
 * and each variant's reorder level (so the form opens on the saved threshold instead of zero).
 */
export async function readProductForEdit(productId) {
  const { product, barcodes, barcodeIds } = await catalogApi.productForEdit(productId);
  const ids = (product.variants ?? []).map((v) => v.id);
  let reorder = {};
  if (ids.length) {
    // The stock screen's rows are the only read that carries reorder_level.
    const rows = await posApi.stock("?limit=500").catch(() => []);
    const wanted = new Set(ids);
    const list = Array.isArray(rows) ? rows : [];
    reorder = Object.fromEntries(
      list.filter((r) => wanted.has(r.variant_id)).map((r) => [r.variant_id, r.reorder_level ?? 0]),
    );
  }
  return productToForm(product, barcodes, barcodeIds, reorder);
}

/** One product from the backend, shaped for the editor form. A temporary failure is retried, a 404 is not. */
export function productEditQueryOptions(productId) {
  return {
    queryKey: [...CATALOG_KEY, "edit", productId],
    staleTime: 0,
    retry: shouldRetryEditLoad,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 6000),
    queryFn: () => readProductForEdit(productId),
  };
}

export function useProductForEdit(productId) {
  return useQuery(productEditQueryOptions(productId));
}

/** Save an edit: only what changed is sent; the POS catalog is refreshed so a new price sells at once. */
export function useUpdateProduct(productId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ before, after, warehouseId }) => {
      const plan = planProductEdit(before, after);
      if (plan.empty) return { changed: false };
      await catalogApi.applyProductEdit(productId, plan, { warehouseId });
      return { changed: true };
    },
    onSettled: () => qc.invalidateQueries({ queryKey: CATALOG_KEY }),
  });
}
