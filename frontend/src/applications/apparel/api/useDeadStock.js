import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { deadStockDays, deadStockRows, deadStockTotals } from "./deadStockReport";
import { shouldRetryProfit } from "./useProfitReport";

export const DEAD_STOCK_KEY = ["cashier", "dead-stock"];

/** One answer from the server, shaped for the table. Kept separate so it can be tested alone. */
export function shapeDeadStock(data) {
  return { days: deadStockDays(data), rows: deadStockRows(data?.rows ?? []), totals: deadStockTotals(data?.totals) };
}

/**
 * المخزون الراكد: الأيام من إعداد صاحب المتجر، و`days` اختياري بيغيّرها لنظرة واحدة. نفس قاعدة
 * الـ403 بتاعة الربح (مدير أو صاحب محل بس، من غير إعادة محاولة). `enabled` بيخلّيه يتبعت لما
 * تابه يتفتح.
 */
export function useDeadStock({ days = "", enabled = true } = {}) {
  const wanted = Number(days) > 0 ? Number(days) : "";
  return useQuery({
    queryKey: [...DEAD_STOCK_KEY, wanted],
    enabled,
    staleTime: 0,
    retry: shouldRetryProfit,
    queryFn: async () => shapeDeadStock(await posApi.deadStock(wanted)),
  });
}
