/**
 * The tax tab, arranged the way a merchant fills it in, plus the one question it must answer
 * honestly: "is my e-receipt really going out?".
 *
 * A receipt that is switched on but cannot be built is skipped without any message at the till, so
 * the merchant has to be told here, in words, what is missing. The checks in `readiness` mirror
 * what the server and the authority's validator refuse (backend pos/eta_adapter.py and
 * einvoice/providers/eta/validator.py): a 9-digit tax number, a 4-digit activity code, a branch
 * code and a full branch address. If those rules change there, change them here.
 */

/** The two settings domains this tab reads, in one form. */
export const TAX_DOMAINS = ["business", "einvoice"];

/**
 * The sections, in the order a merchant fills them in. Every setting belongs to exactly one; one the
 * server adds later falls into the last section so it is never silently hidden.
 */
export const SECTIONS = [
  {
    id: "identity",
    title: "بيانات المحل الضريبية",
    hint: "زي ما هي مسجلة في بطاقتك الضريبية. بتظهر في كل إيصال.",
    keys: ["business.legal_name", "business.trade_name", "business.tax_id"],
  },
  {
    id: "pricing",
    title: "الأسعار والضريبة",
    hint: "الضريبة 14%. حدّد إذا كانت أسعارك مسجلة بالضريبة ولا من غيرها.",
    keys: ["einvoice.prices_include_vat", "einvoice.vat_category"],
  },
  {
    id: "payment",
    title: "طريقة الدفع في الإيصال",
    hint: "الإيصال بيقبل طريقة دفع واحدة، والكاشير بيسجل طريقة الدفع الفعلية لكل بيع.",
    keys: ["einvoice.split_payment_rule", "einvoice.default_payment_method"],
  },
  {
    id: "branch",
    title: "الفرع والنشاط",
    hint: "الأكواد والعنوان زي ما هم مسجلين في بوابة الممول بالظبط.",
    keys: [
      "einvoice.branch_code",
      "einvoice.activity_code",
      "einvoice.branch_governate",
      "einvoice.branch_region_city",
      "einvoice.branch_street",
      "einvoice.branch_building_number",
    ],
  },
  {
    id: "advanced",
    title: "إعدادات متقدمة",
    hint: "غالبًا ما تحتاجش تغيّرها.",
    keys: ["einvoice.unit_code", "einvoice.delivery_mode", "einvoice.warn_hours_before_deadline"],
    rest: true, // anything not placed above lands here
  },
];

/** On/off and the confirmation belong to the status panel, not to a section. */
const PANEL_KEYS = new Set(["einvoice.eta_enabled", "einvoice.settings_confirmed"]);

const PLACED = new Set(SECTIONS.flatMap((s) => s.keys));

/** The definitions that belong in one section, in the section's own order. */
export function sectionDefs(section, defs) {
  const by = Object.fromEntries((defs ?? []).map((d) => [d.key, d]));
  const own = section.keys.map((k) => by[k]).filter(Boolean);
  if (!section.rest) return own;
  // Only a NEW e-receipt setting lands here. `business.*` also holds things that are not tax at all
  // (business type, size/colour matrix, batches, weighing...), which must never appear on this tab.
  const strays = (defs ?? []).filter((d) => d.key.startsWith("einvoice.") && !PLACED.has(d.key) && !PANEL_KEYS.has(d.key));
  return [...own, ...strays];
}

/**
 * Plain words for the settings that read like codes. The server keeps the code; the merchant sees
 * a name. Only the label and the description are replaced.
 */
export const FRIENDLY = {
  "einvoice.delivery_mode": {
    label: "طريقة تسليم البضاعة",
    description: "لمحل بيبيع من مكانه سيبها زي ما هي. غيّرها بس لو بتوصّل الطلبات.",
  },
  "einvoice.unit_code": {
    label: "وحدة البيع في الإيصال",
    description: "القطعة هي الأغلب للمحلات. اتركها كما هي إلا إذا طلبت المصلحة غير ذلك.",
  },
  "einvoice.warn_hours_before_deadline": {
    label: "نبّهني قبل ما مهلة تصحيح الإيصال المرفوض تخلص (بالساعات)",
    description: "إذا رفضت المصلحة إيصالاً، فلديك مهلة لتصحيحه. هذه عدد الساعات التي تُنبَّه فيها قبل انتهائها.",
  },
  "einvoice.default_payment_method": {
    label: "طريقة الدفع لو البيع ما سجّلش طريقة",
    description: "تُستخدم فقط إذا سُجّل البيع دون طريقة دفع (بيع على الحساب مثلاً). وإلا فيأخذ الإيصال طريقة الدفع الفعلية.",
  },
  "einvoice.vat_category": {
    label: "الأصناف خاضعة للضريبة؟",
    description: "تنطبق على كل أصناف المحل. معظم المحلات: خاضع للضريبة.",
  },
};

const clean = (v) => String(v ?? "").trim();
const asciiDigits = (v) => /^[0-9]+$/.test(v);

/**
 * Is the e-receipt really going out, and if not, exactly why. `values` maps a setting key to its
 * current value. Everything missing is listed at once so the merchant fixes it in one go.
 */
export function readiness(values) {
  const v = values ?? {};
  if (!v["einvoice.eta_enabled"]) {
    return { state: "off", missing: [], reasons: [] };
  }
  const missing = [];
  const taxId = clean(v["business.tax_id"]);
  if (!(asciiDigits(taxId) && taxId.length === 9)) {
    // Arabic-Indic digits look right on screen but the authority only takes 0-9: say so.
    missing.push(/[\u0660-\u0669\u06F0-\u06F9]/.test(taxId) ? "الرقم الضريبي (اكتبه بأرقام إنجليزية 0-9، 9 أرقام)" : "الرقم الضريبي (9 أرقام)");
  }
  if (!clean(v["business.legal_name"]) && !clean(v["business.trade_name"])) missing.push("اسم المحل");
  if (!clean(v["einvoice.branch_code"])) missing.push("كود الفرع");
  const activity = clean(v["einvoice.activity_code"]);
  if (!(asciiDigits(activity) && activity.length === 4)) {
    missing.push(/[\u0660-\u0669\u06F0-\u06F9]/.test(activity) ? "كود النشاط (اكتبه بأرقام إنجليزية 0-9، 4 أرقام)" : "كود النشاط (4 أرقام)");
  }
  if (!clean(v["einvoice.branch_governate"])) missing.push("المحافظة");
  if (!clean(v["einvoice.branch_region_city"])) missing.push("المدينة أو المنطقة");
  if (!clean(v["einvoice.branch_street"])) missing.push("الشارع");
  if (!clean(v["einvoice.branch_building_number"])) missing.push("رقم المبنى");

  const reasons = [];
  if (!v["einvoice.settings_confirmed"]) reasons.push("لم تؤكد بعد إعدادات الأسعار والضريبة والدفع. أكّدها ليبدأ الإيصال.");
  if (missing.length) reasons.push(`بيانات ناقصة أو غلط: ${missing.join("، ")}.`);
  return reasons.length ? { state: "blocked", missing, reasons } : { state: "running", missing: [], reasons: [] };
}
