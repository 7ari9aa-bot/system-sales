import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { movementsFromApi, movementsQuery } from "./movementsAdapter";

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
