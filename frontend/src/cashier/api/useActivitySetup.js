import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { catalogApi } from "./catalogApi";
import { normaliseSetup } from "@/cashier/lib/activitySetup";
import { SHOP_OPTIONS_KEY, STOCK_SCREENS_KEY } from "./useShopOptions";

export const ACTIVITY_SETUP_KEY = ["activity-setup"];

/**
 * Whether this owner is due to be asked what kind of shop this is, and the raw answer (for the
 * settings screen). Never traps anyone: while the answer is loading, or if it cannot be read, the
 * result is "do not ask", so a failed read shows the app exactly as it was.
 */
export function useActivitySetup() {
  const q = useQuery({
    queryKey: ACTIVITY_SETUP_KEY,
    staleTime: 60 * 1000,
    retry: 0,
    queryFn: () => catalogApi.activitySetup(),
  });
  return { setup: normaliseSetup(q.data), raw: q.data ?? null, isLoading: q.isLoading };
}

// Answering changes what the shop shows (its size and colour lists and which stock screens), so
// everything that reads them is refreshed once the server has answered.
function useRefreshAfter() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ACTIVITY_SETUP_KEY }),
      qc.invalidateQueries({ queryKey: SHOP_OPTIONS_KEY }),
      qc.invalidateQueries({ queryKey: STOCK_SCREENS_KEY }),
    ]);
}

/** Send the owner's answer. The body comes from `completeBody`, which never carries a sector we do not serve. */
export function useCompleteActivitySetup() {
  const refresh = useRefreshAfter();
  return useMutation({
    mutationFn: (body) => catalogApi.completeActivitySetup(body),
    onSuccess: refresh,
  });
}

/** Leave the shop as it is and stop asking. */
export function useSkipActivitySetup() {
  const refresh = useRefreshAfter();
  return useMutation({ mutationFn: () => catalogApi.skipActivitySetup(), onSuccess: refresh });
}

/**
 * Ask the setup again, from settings. It only moves the marker back to "not started", so the gate
 * shows the wizard on the next render; nothing the owner built is touched, and the preset they
 * confirm later fills only the switches they never set.
 */
export function useReopenActivitySetup() {
  const refresh = useRefreshAfter();
  return useMutation({ mutationFn: () => catalogApi.reopenActivitySetup(), onSuccess: refresh });
}
