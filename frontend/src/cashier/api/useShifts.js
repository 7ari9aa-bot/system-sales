import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/AuthContext";
import { posApi } from "./posApi";
import { bootstrapPos, chooseRegister, pickMyShift, resolveShiftState, resolveWorkingSession } from "./shiftState";
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

export const WORKING_SESSION_KEY = ["cashier", "working-session"];

/** The sales screen's till: today's session from the server, no shift to open. See resolveWorkingSession. */
export function useWorkingSession({ registerId = null } = {}) {
  return useQuery({
    queryKey: [...WORKING_SESSION_KEY, registerId],
    queryFn: () => resolveWorkingSession({ registerId }),
    staleTime: 60_000,
  });
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

const NONE_TEXT = {
  all_busy: "كل أجهزة الكاشير عليها ورديات مفتوحة. أغلق وردية أو أضف جهازًا جديدًا.",
  picked_unavailable: "الجهاز الذي اخترته لم يعد متاحًا. اختر جهازًا آخر.",
  no_register: "لا يوجد جهاز كاشير نشط.",
};

/** What the Open Shift button needs to know before it can ask the server: which drawers are free right now. */
export async function loadOpenChoice() {
  const [registers, open] = await Promise.all([posApi.listRegisters(), posApi.listSessions("status=OPEN")]);
  return chooseRegister(registers ?? [], open ?? []);
}

/** The Open Shift button, as a plain function so it can be tested without React. `registerId` is the cashier's explicit pick. */
export async function openShiftFlow({ openingCash, registerId = null, userId = null }) {
  let registers;
  let open;
  try {
    [registers, open] = await Promise.all([posApi.listRegisters(), posApi.listSessions("status=OPEN")]);
  } catch (err) {
    throw new Error(err?.status === 403 ? "ليست لديك صلاحية فتح وردية." : err?.message || "تعذّر قراءة أجهزة الكاشير");
  }
  if (!(registers ?? []).some((r) => r?.is_active !== false)) {
    const first = await bootstrapPos(); // first use: warehouse -> profile -> register
    return posApi.openSession(first.id, { openingFloat: openingCash });
  }
  // One open shift per cashier: this person already has a drawer open.
  if (pickMyShift(open ?? [], userId)) throw new Error("هناك وردية مفتوحة بالفعل");
  // Read the shop's real situation instead of assuming "the first drawer is mine".
  const choice = chooseRegister(registers ?? [], open ?? [], registerId);
  if (choice.status === "choose") throw Object.assign(new Error("اختر جهاز الكاشير الذي ستعمل عليه"), { code: "register_required" });
  if (choice.status === "none") throw new Error(NONE_TEXT[choice.reason] ?? "تعذّر اختيار جهاز الكاشير");
  return posApi.openSession(choice.register.id, { openingFloat: openingCash });
}

export function useOpenShift() {
  const refresh = useRefresh();
  const { user } = useAuth();
  const userId = user?.id ?? null;
  return useMutation({ mutationFn: (args) => openShiftFlow({ ...args, userId }), onSuccess: refresh });
}

/** The drawers a cashier could open a shift on right now. Read only while the open-shift dialog is up. */
export function useOpenChoice(enabled) {
  return useQuery({ queryKey: ["cashier", "open-choice"], queryFn: loadOpenChoice, enabled, staleTime: 0, gcTime: 0 });
}

export function useCloseShift() {
  const qc = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ sessionId, countedCash }) => posApi.closeSession(sessionId, { countedCash }),
    // The server clears the shift's parked carts in the close; drop the cached lists so none shows stale.
    onSuccess: (_closed, { sessionId }) => {
      qc.removeQueries({ queryKey: ["cashier", "held", sessionId] });
      return refresh();
    },
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
