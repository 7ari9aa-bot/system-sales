import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { posApi } from "./posApi";
import { createIntentStore } from "./intentStore";
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
 * One Idempotency-Key per user intention (see intentStore.js): re-sending the same Save reuses the key so a lost
 * response cannot book the expense twice; a corrected Save gets a new key instead of a guaranteed 409.
 */
function useIntentMutation(call) {
  const refresh = useRefresh();
  const store = useRef(null);
  if (!store.current) store.current = createIntentStore();
  return useMutation({
    mutationFn: async ({ id, ...args }) => {
      const slot = id ?? "new";
      const intent = store.current.take(slot, args);
      const result = await call(args, intent);
      store.current.done(slot);
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
