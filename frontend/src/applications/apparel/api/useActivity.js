import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { activityPageFromApi, activityQuery } from "./activityAdapter";

export const ACTIVITY_KEY = ["cashier", "activity"];

/**
 * The operations timeline, newest first, filtered ON THE SERVER (so a filter reaches rows older than
 * what is loaded) and paged by an opaque cursor. `filters` = { term, type, employeeId, from, to }.
 */
export function useActivity(filters) {
  return useInfiniteQuery({
    queryKey: [...ACTIVITY_KEY, "feed", filters],
    initialPageParam: "",
    queryFn: async ({ pageParam }) => activityPageFromApi(await posApi.activityFeed(activityQuery({ ...filters, cursor: pageParam }))),
    getNextPageParam: (last) => last.next ?? undefined,
  });
}

/** Counts per kind for the window (the cards under the table). Cheap: one GROUP BY. */
export function useActivitySummary({ from = "", to = "" } = {}) {
  const p = new URLSearchParams();
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  return useQuery({
    queryKey: [...ACTIVITY_KEY, "summary", from, to],
    queryFn: async () => (await posApi.activitySummary(p.toString()))?.counts ?? {},
  });
}
