import { useQuery } from "@tanstack/react-query";
import { posApi } from "./posApi";

/** Who the cashier can ask. Only fetched while the approval dialog is open. */
export function useApprovers(enabled) {
  return useQuery({
    queryKey: ["cashier", "approvers"],
    queryFn: () => posApi.approvers(),
    enabled,
    staleTime: 30_000,
  });
}
