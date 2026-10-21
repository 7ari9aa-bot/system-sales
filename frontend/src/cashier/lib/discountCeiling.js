/**
 * The discount ceiling is the till profile's `discount_ceiling_pct`: the number the SERVER enforces on every sale
 * (above it a manager PIN is needed). The screens read and edit that same number, never a local copy.
 */

/** Percent the cashier may give without a manager, as a number. Unknown or invalid reads as 0: no discount without a manager. */
export function ceilingPct(profile) {
  const n = Number(profile?.discount_ceiling_pct);
  return Number.isFinite(n) && n >= 0 ? Math.min(n, 100) : 0;
}

/** What the settings box sends: a 0 to 100 percent with at most 2 decimals, or an Arabic message. */
export function parseCeilingInput(raw) {
  const text = String(raw ?? "").trim();
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(text)) return { ok: false, message: "اكتب نسبة من 0 إلى 100 (حتى رقمين بعد الفاصلة)" };
  if (Number(text) > 100) return { ok: false, message: "النسبة لا تتجاوز 100%" };
  return { ok: true, value: Number(text).toFixed(2) };
}
