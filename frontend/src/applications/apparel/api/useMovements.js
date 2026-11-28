import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { describeMovements, movementsFromApi, movementsQuery } from "./movementsAdapter";
import { STOCK_LIMIT, stockQuery, stockRowFromApi } from "./stockAdapter";

export const MOVEMENTS_KEY = ["cashier", "movements"];

/** The stock ledger of one variant, newest first. Only runs once a variant is chosen. */
export function useVariantMovements(variantId) {
  const query = movementsQuery({ variantId });
  return useQuery({
    queryKey: [...MOVEMENTS_KEY, query],
    queryFn: async () => movementsFromApi(await posApi.movements(query)),
    enabled: !!variantId,
  });
}

/** The whole stock ledger (newest first) with each row's product, colour/size and SKU filled in. */
export function useAllMovements({ reason, limit = 500 } = {}) {
  const query = movementsQuery({ reason, limit });
  return useQuery({
    queryKey: [...MOVEMENTS_KEY, "all", query],
    queryFn: async () => {
      const [ledger, stock] = await Promise.all([posApi.movements(query), posApi.stock(stockQuery({ limit: STOCK_LIMIT }))]);
      const variants = new Map(stock.map(stockRowFromApi).map((r) => [r.id, r]));
      return describeMovements(movementsFromApi(ledger), variants);
    },
    placeholderData: (previous) => previous,
  });
}
