/**
 * Where is the till right now? One explicit state instead of every screen guessing.
 *
 *   loading -> needs_setup (who: "manager" | "self") | forbidden | error
 *           -> no_open_shift (register) -> open (register, session)
 *
 * Permissions are split in the backend: creating a profile/register needs
 * settings:write (a manager), selling/opening a shift needs orders:write (a cashier).
 * So a cashier on a fresh shop gets "ask your manager", a manager gets a Set up button.
 */
import { api } from "@/lib/api";
import { posApi } from "./posApi";

export const MAIN_CODE = "MAIN";

const isActive = (r) => r && r.is_active !== false;

function failure(err) {
  const status = err?.status ?? 0;
  if (status === 401) return { status: "unauthorized" };
  if (status === 403) return { status: "forbidden" };
  return { status: "error", message: err?.message ?? "unknown error", retryable: status === 0 || status >= 500 };
}

/** Resolve the state of the (single) shop's till. */
export async function resolveShiftState({ canConfigure = false } = {}) {
  let registers;
  try {
    registers = (await posApi.listRegisters()) ?? [];
  } catch (err) {
    return failure(err);
  }
  const register = registers.find(isActive);
  if (!register) return { status: "needs_setup", who: canConfigure ? "self" : "manager" };

  try {
    const open = (await posApi.listSessions(`status=OPEN&register_id=${encodeURIComponent(register.id)}`)) ?? [];
    // Trust the server filter, but never trust it blindly with money screens.
    const mine = open.find((s) => s.status === "OPEN" && s.register_id === register.id);
    if (!mine) return { status: "no_open_shift", register };
    const session = await posApi.getSession(mine.id); // adds inflow/outflow/expected_now
    return { status: "open", register, session };
  } catch (err) {
    return failure(err);
  }
}

/**
 * Manager-only, idempotent first-use setup: default warehouse -> profile MAIN -> register MAIN.
 * Safe to call twice: returns the existing register without writing anything.
 * (Codes are unique per tenant in the DB, so even a race converges on one row.)
 */
export async function bootstrapPos() {
  const existing = ((await posApi.listRegisters()) ?? []).find(isActive);
  if (existing) return existing;

  // A brand-new shop has no warehouse and nothing else can create one; this endpoint is
  // manager-only and repeat-safe (returns the existing default, or bootstraps "Main").
  const warehouse = await api("/warehouses/ensure-default", { method: "POST" });
  if (!warehouse?.id) throw new Error("Could not prepare a warehouse for this shop.");

  const profiles = (await posApi.listProfiles()) ?? [];
  let profile = profiles.find((p) => p.code === MAIN_CODE && isActive(p));
  if (!profile) {
    profile = await api("/pos/profiles", {
      method: "POST",
      body: {
        name: "Main",
        code: MAIN_CODE,
        warehouse_id: warehouse.id,
        allowed_payment_methods: ["cash", "card", "wallet", "bank_transfer"],
        default_payment_method: "cash",
      },
    });
  }

  return api("/pos/registers", {
    method: "POST",
    body: { name: "Main till", code: MAIN_CODE, warehouse_id: warehouse.id, profile_id: profile.id },
  });
}
