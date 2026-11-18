/**
 * The shop-policy screen is drawn from the settings engine's own definitions, so a setting the
 * server starts to enforce shows up here without a new screen, and one it does not enforce never
 * does. The rule the rest of the settings pages follow applies: no field and no "saved" toast for a
 * value nothing reads.
 */

/** The settings an owner can change here: this domain, wired to real behaviour, tenant-wide. */
export function policyDefinitions(definitions, { domain = "pos" } = {}) {
  return (definitions ?? []).filter((d) => d.domain === domain && d.enforced && (d.scopes ?? []).includes("tenant"));
}

/** What the form starts from: the effective value of each setting, as the server resolved it. */
export function startingValues(defs, effective) {
  return Object.fromEntries(defs.map((d) => [d.key, effective?.[d.key]?.value ?? d.default]));
}

/** Only what the owner actually changed, so saving one field never rewrites the others. */
export function changedValues(defs, original, draft) {
  return defs.filter((d) => !sameValue(original[d.key], draft[d.key])).map((d) => ({ key: d.key, value: draft[d.key] }));
}

function sameValue(a, b) {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** A number box holds text while typing; "" means "no limit" only where the setting allows it. */
export function parseNumber(def, text) {
  const raw = String(text ?? "").trim();
  if (raw === "") return def.default === null ? { value: null } : { error: "اكتب رقمًا" };
  const n = Number(raw);
  if (!Number.isFinite(n)) return { error: "اكتب رقمًا صحيحًا" };
  if (def.min_value != null && n < def.min_value) return { error: `الحد الأدنى ${def.min_value}` };
  if (def.max_value != null && n > def.max_value) return { error: `الحد الأقصى ${def.max_value}` };
  return { value: n };
}

/** One reason per line; blanks and repeats dropped, so the list the cashier sees is clean. */
export function parseReasons(text) {
  const seen = new Set();
  const out = [];
  for (const line of String(text ?? "").split("\n")) {
    const v = line.trim();
    if (v && !seen.has(v)) {
      seen.add(v);
      out.push(v);
    }
  }
  return out;
}

export const reasonsToText = (list) => (list ?? []).join("\n");

/** The server's own refusal, in plain words; anything unknown passes through, never hidden. */
export function policyErrorMessage(err) {
  const m = String(err?.message ?? err ?? "");
  if (/permission|403/i.test(m)) return "ليست لديك صلاحية تغيير هذا الإعداد";
  return m || "تعذّر الحفظ";
}
