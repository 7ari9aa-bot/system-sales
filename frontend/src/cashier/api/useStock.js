import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { catalogApi } from "./catalogApi";
import { posApi } from "./posApi";
import { stockQuery, stockRowFromApi, stockSummaryFromApi } from "./stockAdapter";

export const STOCK_KEY = ["cashier", "stock"];

/**
 * The stock grid. Search and the status filter are applied ON THE SERVER (so a filter reaches variants
 * beyond what is loaded and the status can never disagree with the backend rule). Category is filtered
 * by id for the same reason.
 */
export function useStock(filters) {
  const query = stockQuery(filters);
  return useQuery({
    queryKey: [...STOCK_KEY, "rows", query],
    queryFn: async () => (await posApi.stock(query)).map(stockRowFromApi),
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

/** Real categories for the filter (id + name): the grid filters by id on the server. */
export function useStockCategories() {
  return useQuery({
    queryKey: [...STOCK_KEY, "categories"],
    queryFn: async () => (await catalogApi.categories()).map((c) => ({ id: c.id, name: c.name })),
    staleTime: 5 * 60 * 1000,
  });
}
