import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { catalogApi } from "./catalogApi";
import { posApi } from "./posApi";
import { fetchStockRows, materialChoices, seasonChoices, stockQuery, stockRowFromApi, stockSummaryFromApi } from "./stockAdapter";

export const STOCK_KEY = ["cashier", "stock"];

/**
 * The stock grid: EVERY variant matching the filters, not one capped page.
 *
 * Search and the status filter are applied ON THE SERVER (so a filter reaches variants beyond what
 * is loaded and the status can never disagree with the backend rule); the paging is the client's,
 * because the endpoint caps a page at 1,000 and this list is also what the CSV export, the labels
 * and the stocktake sheet read.
 */
export function useStock(filters) {
  const query = stockQuery(filters);
  return useQuery({
    queryKey: [...STOCK_KEY, "rows", query],
    queryFn: async () => (await fetchStockRows(filters, (qs) => posApi.stock(qs))).map(stockRowFromApi),
    placeholderData: (previous) => previous, // keep the old rows on screen while a filter loads
  });
}

/** Totals over EVERY active variant (not the visible page): pieces, alerts, shelf value at cost/retail. */
export function useStockSummary() {
  return useQuery({
    queryKey: [...STOCK_KEY, "summary"],
    queryFn: async () => stockSummaryFromApi(await posApi.stockSummary()),
  });
}

/** Change a variant's reorder level; the grid, the alert count and the dashboard card re-read after. */
export function useSetReorderLevel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ variantId, level }) => posApi.setReorderLevel(variantId, level),
    onSuccess: () => qc.invalidateQueries({ queryKey: STOCK_KEY }),
  });
}

/** One reorder level for every active size of a model (a clothing size run). */
export function useSetProductReorderLevel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ productId, level }) => posApi.setProductReorderLevel(productId, level),
    onSuccess: () => qc.invalidateQueries({ queryKey: STOCK_KEY }),
  });
}

/** Real categories for the filter (id + name): the grid filters by id on the server. */
export function useStockCategories() {
  return useQuery({
    queryKey: [...STOCK_KEY, "categories"],
    queryFn: async () => (await catalogApi.categories()).map((c) => ({ id: c.id, name: c.name })),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * The seasons this shop has used, for the season filter. Read with NO filter, so picking one season
 * does not make the others vanish from the list. Cached like the categories: it changes only when
 * a product's season is edited.
 */
export function useStockSeasons() {
  return useQuery({
    queryKey: [...STOCK_KEY, "seasons"],
    queryFn: async () => seasonChoices((await posApi.stock(stockQuery())).map(stockRowFromApi)),
    staleTime: 5 * 60 * 1000,
  });
}


/**
 * The materials (fabrics) this shop has used, for the material filter and for the product form's
 * suggestions. Read with NO filter, for the same reason as the seasons: picking one material must
 * not make the others vanish from the list. Cached like the categories: it changes only when a
 * product's material is edited.
 */
export function useStockMaterials() {
  return useQuery({
    queryKey: [...STOCK_KEY, "materials"],
    queryFn: async () => materialChoices((await posApi.stock(stockQuery())).map(stockRowFromApi)),
    staleTime: 5 * 60 * 1000,
  });
}
