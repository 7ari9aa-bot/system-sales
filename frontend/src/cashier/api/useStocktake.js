import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { newIntent, posApi } from "./posApi";
import { STOCK_KEY, useStock } from "./useStock";
import { sheetFromApi } from "./stocktakeAdapter";

export const STOCKTAKE_KEY = ["cashier", "stocktake"];

/** The newest count, if it is still OPEN (one shop first: at most one open count exists). */
export function useOpenStocktakeId() {
  return useQuery({
    queryKey: [...STOCKTAKE_KEY, "list"],
    queryFn: async () => {
      const list = await posApi.stocktakes();
      return list.find((s) => s.status === "OPEN")?.id ?? null;
    },
  });
}

/** The sheet of one count joined with the stock rows (names, colour, size). */
export function useStocktakeSheet(id) {
  const stock = useStock({});
  const detail = useQuery({
    queryKey: [...STOCKTAKE_KEY, "detail", id],
    queryFn: () => posApi.stocktake(id),
    enabled: Boolean(id),
  });
  const sheet = detail.data ? sheetFromApi(detail.data, stock.data ?? []) : null;
  return { sheet, isLoading: detail.isLoading || stock.isLoading, error: detail.error ?? stock.error };
}

function useRefresh() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: STOCKTAKE_KEY }), qc.invalidateQueries({ queryKey: STOCK_KEY })]);
}

/** Start a count. The intent is kept until it succeeds so a retried tap opens ONE count. */
export function useOpenStocktake() {
  const refresh = useRefresh();
  let intent = null;
  return useMutation({
    mutationFn: async (note) => {
      intent ??= newIntent();
      const out = await posApi.openStocktake(note, intent);
      intent = null;
      return out;
    },
    onSuccess: refresh,
  });
}

export function useSaveCounts(id) {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (counts) => posApi.saveStocktakeCounts(id, counts), onSuccess: refresh });
}

/** Approve: the only call that moves stock. One intent per tap, replayed by the server on a retry. */
export function useApproveStocktake(id) {
  const refresh = useRefresh();
  let intent = null;
  return useMutation({
    mutationFn: async () => {
      intent ??= newIntent();
      const out = await posApi.approveStocktake(id, intent);
      intent = null;
      return out;
    },
    onSuccess: refresh,
  });
}

export function useCancelStocktake(id) {
  const refresh = useRefresh();
  return useMutation({ mutationFn: () => posApi.cancelStocktake(id, newIntent()), onSuccess: refresh });
}
