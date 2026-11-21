/**
 * The shop-policy screen is drawn from the settings engine's own definitions, so a setting the
 * server starts to enforce shows up here without a new screen, and one it does not enforce never
 * does. The rule the rest of the settings pages follow applies: no field and no "saved" toast for a
 * value nothing reads.
 */

/** The settings an owner can change here: this domain, wired to real behaviour, tenant-wide. */
export function policyDefinitions(definitions, { domain = "pos" } = {}) {
  const domains = Array.isArray(domain) ? domain : [domain];
  return (definitions ?? []).filter((d) => domains.includes(d.domain) && d.enforced && (d.scopes ?? []).includes("tenant"));
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

/**
 * Plain-Arabic names for the coded choices the authority defines, so a merchant never has to read
 * "CC" or "V004". Keyed by setting, then by the stored value. A choice with no entry shows its
 * raw value, which is honest, just less friendly.
 */
export const CHOICE_LABELS_AR = {
  "einvoice.default_payment_method": {
    C: "نقدي",
    V: "فيزا",
    CC: "نقدي مع مقاول",
    VC: "فيزا مع مقاول",
    VO: "قسيمة",
    PR: "ترويج",
    GC: "بطاقة هدايا",
    P: "نقاط",
    O: "أخرى (محفظة، إنستاباي، تحويل)",
  },
  "einvoice.split_payment_rule": {
    largest: "الطريقة اللي دفعت أكبر مبلغ",
    cash_first: "نقدي لو فيه أي مبلغ نقدي",
  },
  "einvoice.vat_category": {
    taxable: "خاضع للضريبة (14%)",
    exempt: "معفى من الضريبة",
    non_taxable: "غير خاضع للضريبة",
  },
  "einvoice.delivery_mode": {
    FC: "من مكان الشركة",
    TO: "نقل بواسطة آخرين",
    TC: "نقل بواسطة الشركة",
  },
};

/** The label to show for one stored choice. */
export function choiceLabel(def, value) {
  return CHOICE_LABELS_AR[def.key]?.[value] ?? value;
}

/** Free text (a branch code, a street). Kept as text: "007" must never become 7. May be empty. */
export function parseText(def, text) {
  const v = String(text ?? "").trim();
  if (def.max_length != null && v.length > def.max_length) return { error: `الحد الأقصى ${def.max_length} حرفًا` };
  return { value: v };
}

/** One of the server's own allowed choices, never anything typed by hand. */
export function parseChoice(def, value) {
  if (!(def.allowed_values ?? []).includes(value)) return { error: "اختر قيمة من القائمة" };
  return { value };
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
