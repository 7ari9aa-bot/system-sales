import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/AuthContext";
import { posApi } from "./posApi";
import { bootstrapPos, resolveShiftState } from "./shiftState";
import { shiftsFromApi } from "./shiftAdapter";

export const SHIFTS_KEY = ["cashier", "shifts"];
export const SHIFT_STATE_KEY = ["cashier", "shift-state"];

/** Ledger of shifts (newest first) with per-method figures from each shift's report. */
export function useShifts({ employees = {} } = {}) {
  return useQuery({
    queryKey: SHIFTS_KEY,
    queryFn: async () => {
      const sessions = (await posApi.listSessions()) ?? [];
      const entries = await Promise.all(sessions.map(async (s) => [s.id, await posApi.report(s.id).catch(() => null)]));
      return shiftsFromApi(sessions, Object.fromEntries(entries), { employees });
    },
  });
}

/** needs_setup / no_open_shift / open / forbidden / error (see shiftState.js). */
export function useShiftState({ canConfigure = false } = {}) {
  const { user } = useAuth();
  const userId = user?.id ?? null; // so a cashier lands on THEIR drawer, not the shop's first one
  return useQuery({ queryKey: [...SHIFT_STATE_KEY, canConfigure, userId], queryFn: () => resolveShiftState({ canConfigure, userId }) });
}

/** Live figures for the close dialog, computed by the backend from the ledger. */
export function useClosePreview(sessionId, enabled) {
  return useQuery({
    queryKey: ["cashier", "close-preview", sessionId],
    queryFn: () => posApi.closePreview(sessionId),
    enabled: Boolean(sessionId) && enabled,
    staleTime: 0,
    gcTime: 0,
  });
}

/** Number of carts still parked on a shift. They cannot be restored once the shift is closed. */
export function useHeldCount(sessionId, enabled) {
  return useQuery({
    queryKey: ["cashier", "held-count", sessionId],
    queryFn: async () => ((await posApi.heldCarts(sessionId)) ?? []).length,
    enabled: Boolean(sessionId) && enabled,
    staleTime: 0,
    gcTime: 0,
  });
}

function useRefresh() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: SHIFTS_KEY }), qc.invalidateQueries({ queryKey: SHIFT_STATE_KEY })]);
}

/** The Open Shift button, as a plain function so it can be tested without React. */
export async function openShiftFlow({ openingCash }) {
  const state = await resolveShiftState({ canConfigure: true });
  if (state.status === "open") throw new Error("هناك وردية مفتوحة بالفعل");
  let registerId;
  if (state.status === "needs_setup") registerId = (await bootstrapPos()).id; // first use: warehouse -> profile -> register
  else if (state.status === "no_open_shift") registerId = state.register.id;
  else throw new Error(state.message || "تعذّر فتح الوردية. تأكد من الصلاحيات ثم حاول مرة أخرى.");
  return posApi.openSession(registerId, { openingFloat: openingCash });
}

export function useOpenShift() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: openShiftFlow, onSuccess: refresh });
}

export function useCloseShift() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ sessionId, countedCash }) => posApi.closeSession(sessionId, { countedCash }),
    onSuccess: refresh,
  });
}

/** Record a manual drawer movement. `intent` must stay the same across retries of ONE
 *  attempt (so a dropped response cannot post twice) and be renewed after a success. */
export function useCashMovement() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ sessionId, direction, reason, amount, intent }) =>
      posApi.cashMovement(sessionId, { direction, reason, amount }, intent),
    onSuccess: refresh,
  });
}
