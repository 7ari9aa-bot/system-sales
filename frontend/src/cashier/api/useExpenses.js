import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { newIntent, posApi } from "./posApi";
import { categoriesFromApi, expensesFromApi } from "./expensesAdapter";
import { SHIFTS_KEY, SHIFT_STATE_KEY } from "./useShifts";

export const EXPENSES_KEY = ["cashier", "expenses"];
export const EXPENSE_CATEGORIES_KEY = ["cashier", "expense-categories"];

export function useExpenseCategories() {
  return useQuery({
    queryKey: EXPENSE_CATEGORIES_KEY,
    queryFn: async () => categoriesFromApi(await posApi.expenseCategories()),
    staleTime: 5 * 60 * 1000,
  });
}

/** Expenses newest first, mapped to screen rows. `users` maps user id -> display name. */
export function useExpenses({ categories = [], users = {} } = {}) {
  return useQuery({
    queryKey: [...EXPENSES_KEY, categories.map((c) => c.id).join(","), Object.keys(users).length],
    queryFn: async () => expensesFromApi(await posApi.listExpenses(), { categories, users }),
    enabled: categories.length > 0,
  });
}

function useRefresh() {
  const qc = useQueryClient();
  // A cash expense changes the shift's drawer, so the shift figures must be re-read too.
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: EXPENSES_KEY }),
      qc.invalidateQueries({ queryKey: SHIFTS_KEY }),
      qc.invalidateQueries({ queryKey: SHIFT_STATE_KEY }),
    ]);
}

/**
 * The intent lives as long as the user's intention: a failed Save that is tapped again re-sends
 * the SAME key (so a lost response cannot book the expense twice); a successful one starts a new intent.
 */
function useIntentMutation(call) {
  const refresh = useRefresh();
  // useRef, not a plain Map: a Map built in the hook body is new on every render, which would hand a retry a
  // fresh key and defeat the whole point (the server could not tell it is the same Save).
  const intents = useRef(new Map()).current;
  return useMutation({
    mutationFn: async ({ id, ...args }) => {
      const slot = id ?? "new";
      const intent = intents.get(slot) ?? newIntent();
      intents.set(slot, intent);
      const result = await call(args, intent);
      intents.delete(slot);
      return result;
    },
    onSuccess: refresh,
  });
}

export function usePostExpense() {
  return useIntentMutation(({ payload }, intent) => posApi.createExpense(payload, intent));
}

export function useVoidExpense() {
  return useIntentMutation(({ expenseId, reason }, intent) => posApi.voidExpense(expenseId, { reason }, intent));
}
