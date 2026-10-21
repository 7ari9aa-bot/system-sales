import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { catalogApi } from "./catalogApi";
import { CATALOG_KEY } from "./usePosSale";
import { planProductEdit, productToForm } from "./productEdit";

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
export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const needsStock = (input.variants ?? []).some((v) => Number(v.stock) > 0);
      const warehouseId = needsStock ? await defaultWarehouseId() : undefined;
      return catalogApi.createProduct(input, { warehouseId });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: CATALOG_KEY }),
  });
}

/** Every SKU that exists in the backend now (used to pick a free SKU base). Includes archived products. */
export function useExistingSkus() {
  return useQuery({
    queryKey: [...CATALOG_KEY, "skus"],
    staleTime: 0,
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

/** One product from the backend, shaped for the editor form. An error means it does not exist. */
export function useProductForEdit(productId) {
  return useQuery({
    queryKey: [...CATALOG_KEY, "edit", productId],
    staleTime: 0,
    retry: false,
    queryFn: async () => {
      const { product, barcodes } = await catalogApi.productForEdit(productId);
      return productToForm(product, barcodes);
    },
  });
}

/** Save an edit: only what changed is sent; the POS catalog is refreshed so a new price sells at once. */
export function useUpdateProduct(productId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ before, after }) => {
      const plan = planProductEdit(before, after);
      if (plan.empty) return { changed: false };
      await catalogApi.applyProductEdit(productId, plan);
      return { changed: true };
    },
    onSettled: () => qc.invalidateQueries({ queryKey: CATALOG_KEY }),
  });
}
