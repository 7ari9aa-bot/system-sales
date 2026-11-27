import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { sellThroughQuery, sellThroughRows, sellThroughTotals } from "./sellThroughReport";
import { shouldRetryProfit } from "./useProfitReport";

export const SELL_THROUGH_KEY = ["cashier", "sell-through"];

/** One answer from the server, shaped for the table. Kept separate so it can be tested alone. */
export function shapeSellThrough(data) {
  return { rows: sellThroughRows(data?.rows ?? []), totals: sellThroughTotals(data?.totals) };
}

/**
 * التصريف في فترة، مفلتر بالعلامة والموسم والخامة. نفس استعلام الربح (نهاية الفترة مفتوحة)، ونفس
 * قاعدة الـ403: صاحب المتجر، والمدير لو صاحب المتجر سمح، فالطلب مش بيتعاد. `enabled` بيخلّيه يتبعت لما تابه يتفتح.
 */
export function useSellThrough({ period = "7d", brandId = "", season = "", material = "", enabled = true } = {}) {
  const query = sellThroughQuery({ period, brandId, season, material });
  return useQuery({
    queryKey: [...SELL_THROUGH_KEY, query],
    enabled,
    staleTime: 0,
    retry: shouldRetryProfit,
    queryFn: async () => shapeSellThrough(await posApi.sellThrough(query)),
  });
}
