import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { profitQuery, profitRows, profitTotals } from "./profitReport";

export const PROFIT_KEY = ["cashier", "profit-report"];

/**
 * A 403 means this user may not see cost and profit at all, and a 401 means the session is gone:
 * retrying either just hits the server again for the same answer. Everything else gets one retry,
 * so a flaky connection does not leave an empty report on screen.
 */
export function shouldRetryProfit(failureCount, error) {
  const status = Number(error?.status) || 0;
  if (status === 401 || status === 403) return false;
  return failureCount < 1;
}

/** One answer from the server, shaped for the table. Kept separate so it can be tested alone. */
export function shapeProfit(data) {
  return { rows: profitRows(data?.rows ?? []), totals: profitTotals(data?.totals) };
}

/**
 * الربح في فترة، مفلتر بالعلامة والموسم والخامة. الاستعلام نفسه من profitQuery (نهاية الفترة مفتوحة،
 * فاليوم داخل الحساب). الـ403 مش بيتعاد: المستخدم مش من حقه يشوف التكلفة والربح، وإعادة المحاولة
 * مش هتغيّر ده.
 *
 * `enabled` بيخلّي الطلب يتبعت لما التاب بتاعه يتفتح بس: كاشير بيدخل شاشة التقارير مش محتاج
 * طلب بيترفض بـ403 ويسجّل خطأ كل مرة، والمدير بياخد التقرير أول ما يفتح التاب.
 */
export function useProfitReport({ period = "7d", brandId = "", season = "", material = "", enabled = true } = {}) {
  const query = profitQuery({ period, brandId, season, material });
  return useQuery({
    // The query string IS the cache key: two different windows can never share an answer.
    queryKey: [...PROFIT_KEY, query],
    enabled,
    staleTime: 0,
    retry: shouldRetryProfit,
    // The SAME query string that is the cache key goes to the server: asking again at midnight
    // must not fetch a different window than the one the key names.
    queryFn: async () => shapeProfit(await posApi.profitByVariant(query)),
  });
}
