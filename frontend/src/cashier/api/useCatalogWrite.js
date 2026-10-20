import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { catalogApi } from "./catalogApi";
import { CATALOG_KEY } from "./usePosSale";

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
