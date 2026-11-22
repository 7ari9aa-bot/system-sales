/**
 * Import Center: the calls and the pure rules behind the import screen.
 *
 * The backend (`/imports/sessions`) takes the raw file as the request body and re-checks the type,
 * the size (20 MB) and the contents. We check the same cheap things first so the merchant gets a
 * clear message before anything uploads. Every number shown on screen comes from the server's
 * `stats`; nothing here counts rows or decides what will be imported.
 */
import { api, apiUrl, fetchWithTimeout } from "@/lib/api";

export const MAX_IMPORT_BYTES = 20 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".xlsx", ".csv"];
const REFUSED_EXTENSIONS = [".xls", ".xlsm", ".xlsb"];

const seg = (v) => encodeURIComponent(String(v));
const base = (id) => `/imports/sessions/${seg(id)}`;

/** Where each session sits in the flow. The server's `status` is the only source of truth. */
export const STATUS_LABEL = {
  analyzed: "تم رفع الملف",
  mapped: "تم ربط الأعمدة",
  validated: "جاهز للمراجعة",
  running: "جارٍ الاستيراد",
  completed: "اكتمل",
  cancelled: "أُلغي",
  failed: "فشل",
};

/** A session in these states is still moving on its own: the screen keeps asking for it. */
export const ACTIVE_STATUSES = ["running"];
export const FINISHED_STATUSES = ["completed", "cancelled", "failed"];

export const isFinished = (status) => FINISHED_STATUSES.includes(status);

export const SHEET_LABEL = {
  Products: "المنتجات",
  Variants: "الأصناف (اللون والمقاس)",
  "Opening Stock": "رصيد أول المدة",
  Images: "صور المنتجات (روابط)",
};

/** What each validation code means to a merchant. Unknown codes fall back to a generic line. */
const ERROR_TEXT = {
  required: "حقل مطلوب فارغ",
  no_identity: "الصف بلا اسم ولا SKU ولا باركود",
  duplicate_in_file: "مكرر داخل الملف",
  barcode_taken: "الباركود مستخدم لصنف آخر",
  sku_belongs_to_other_product: "هذا الـ SKU يخص منتجًا آخر",
  unknown_sku: "لا يوجد صنف بهذا الـ SKU",
  not_a_link: "الصورة يجب أن تكون رابطًا كاملًا يبدأ بـ http أو https",
  too_many_images: "عدد صور هذا الـ SKU أكبر من الحد المسموح (10)",
  image_unreachable: "تعذّر تنزيل الصورة من الرابط (الرابط لا يعمل أو غير متاح للعامة)",
  not_an_image: "الرابط لا يشير إلى صورة حقيقية (JPEG أو PNG أو GIF أو WebP أو BMP)",
  storage_unavailable: "تعذّر حفظ الصورة الآن. أعد المحاولة لاحقًا",
  unknown_product: "المنتج غير موجود في الملف أو في المتجر",
  unknown_warehouse: "المخزن غير موجود",
  opening_stock_already_set: "رصيد أول المدة مسجّل لهذا الصنف من قبل",
  not_a_number: "القيمة ليست رقمًا",
  not_whole: "الكمية يجب أن تكون عددًا صحيحًا",
  not_positive: "القيمة يجب أن تكون أكبر من صفر",
  negative: "القيمة لا يمكن أن تكون سالبة",
  too_large: "القيمة كبيرة جدًا",
  too_long: "النص أطول من المسموح",
  has_spaces: "القيمة تحتوي على مسافات",
  bad_status: "الحالة غير معروفة",
  scientific_notation: "الباركود تحوّل إلى صيغة علمية (مثل 6.22E+12). اجعل العمود نصًّا في Excel ثم أعد الحفظ",
};

export const errorText = (code) => ERROR_TEXT[code] ?? "قيمة غير صالحة";

/** null when the file can be uploaded, otherwise the reason (Arabic, shown to the merchant). */
export function importFileProblem(file) {
  if (!file) return "اختر ملفًا أولًا";
  const name = String(file.name ?? "").toLowerCase();
  if (REFUSED_EXTENSIONS.some((e) => name.endsWith(e))) return "احفظ الملف بصيغة .xlsx أو .csv ثم ارفعه من جديد";
  if (!ACCEPTED_EXTENSIONS.some((e) => name.endsWith(e))) return "الصيغ المدعومة: Excel (.xlsx) أو CSV";
  if (!(file.size > 0)) return "الملف فارغ";
  if (file.size > MAX_IMPORT_BYTES) return "حجم الملف أكبر من 20 ميجابايت";
  return null;
}

/** Why a call failed, in words for the merchant. The server's own text is never shown as is. */
export function importErrorText(error) {
  const status = error?.status;
  if (status === 413) return "حجم الملف أكبر من 20 ميجابايت";
  if (status === 401 || status === 403) return "ليس لديك صلاحية الاستيراد. تحتاج صلاحية تعديل المنتجات والمخزون معًا.";
  if (status === 409) return "حالة الاستيراد تغيّرت. أعد تحميل الصفحة.";
  if (status === 404) return "جلسة الاستيراد غير موجودة";
  if (status === 429) return "محاولات كثيرة. انتظر قليلًا ثم أعد المحاولة.";
  if (error?.retryable || status === 0) return "تعذّر الاتصال بالخادم. حاول مرة أخرى.";
  if (status === 400 && typeof error?.message === "string" && error.message) return error.message;
  return "تعذّر إكمال العملية";
}

/* ----------------------------------------------------------------------------------- calls */

export const uploadImportFile = (file) => {
  const problem = importFileProblem(file);
  if (problem) return Promise.reject(new Error(problem));
  return api(`/imports/sessions?filename=${seg(file.name)}`, {
    method: "POST",
    body: file,
    rawBody: true,
    contentType: file.type || "application/octet-stream",
  });
};

/** صفوف ملصوقة من Excel: الباك بيحوّلها جلسة استيراد عادية بنفس المراجعة والتحقق. */
export const pasteImportRows = (text) =>
  api("/imports/sessions/paste", { method: "POST", body: { text } });

export const getImportSession = (id, { signal } = {}) => api(base(id), { signal });
export const listImportSessions = () => api("/imports/sessions?limit=10");
export const saveImportMapping = (id, { mapping, options }) =>
  api(`${base(id)}/mapping`, { method: "PUT", body: { mapping, options } });
export const validateImport = (id) => api(`${base(id)}/validate`, { method: "POST" });
export const getImportPreview = (id, { sample = 20, signal } = {}) => api(`${base(id)}/preview?sample=${sample}`, { signal });
export const startImport = (id) => api(`${base(id)}/start`, { method: "POST" });
export const cancelImport = (id) => api(`${base(id)}/cancel`, { method: "POST" });

/**
 * The rows that were refused, as a CSV the merchant opens in Excel (UTF-8 with BOM, so Arabic shows
 * correctly). It is fetched with the session cookie and handed to the browser as a file; a plain
 * link would not carry the cookie when the API lives on another origin.
 */
export async function downloadErrorReport(id) {
  const res = await fetchWithTimeout(apiUrl(`${base(id)}/errors.csv`), { credentials: "include" });
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = "import-errors.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/**
 * The starter workbook (Products, Variants, Opening Stock, Images). Its headers are the ones the column
 * matcher already knows, so a merchant who fills it in sees every column mapped on the next step.
 * Fetched with the session cookie for the same reason as the error report.
 */
export async function downloadTemplate() {
  const res = await fetchWithTimeout(apiUrl("/imports/template.xlsx"), { credentials: "include" });
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = "fihrist-import-template.xlsx";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/**
 * Columns the import will not read, split into the ones that cost the merchant money (stock typed
 * on the wrong sheet: the quantity is silently not loaded) and the ones that are merely unused.
 */
export function ignoredColumnsOf(sheet) {
  const all = sheet?.ignored_columns ?? [];
  return {
    stock: all.filter((c) => c.reason === "stock_on_wrong_sheet").map((c) => c.column),
    other: all.filter((c) => c.reason !== "stock_on_wrong_sheet").map((c) => c.column),
  };
}

/* -------------------------------------------------------------------------------- pure rules */

/**
 * The sheets of a session as the mapping step lists them: each column of the file with the field
 * it is mapped to, in the file's own order. `mapping` is { header: fieldKey | null }.
 */
export function mappingRows(sheet) {
  return Object.entries(sheet?.mapping ?? {}).map(([header, field]) => ({ header, field: field ?? "" }));
}

/** The fields still unmapped on a sheet (the server computes this; we only read it). */
export const missingFields = (sheet) => sheet?.missing_required ?? [];

/** True when every sheet has what it needs, so "check the file" can be offered. */
export function canValidate(session) {
  const sheets = Object.values(session?.sheets ?? {});
  return sheets.length > 0 && sheets.every((s) => missingFields(s).length === 0);
}

/** One field key may be chosen by one column only: the field's other columns must be cleared. */
export function assignField(mapping, header, fieldKey) {
  const next = { ...mapping };
  if (fieldKey) for (const h of Object.keys(next)) if (h !== header && next[h] === fieldKey) next[h] = null;
  next[header] = fieldKey || null;
  return next;
}

/** Totals across the sheets of a validated session, from the server's counters. */
export function totalsOf(stats) {
  const out = { total: 0, valid: 0, invalid: 0, create: 0, update: 0, skip: 0 };
  for (const s of Object.values(stats?.sheets ?? {})) for (const k of Object.keys(out)) out[k] += Number(s?.[k] ?? 0);
  return out;
}

/** Whether "start" is allowed: the file was checked and at least one row can be applied. */
export const canStart = (session) => session?.status === "validated" && totalsOf(session?.stats).valid > 0;

/** Rows the run has dealt with so far (applied, skipped or failed), from the server's counters. */
export const doneOf = (stats) => Number(stats?.applied ?? 0) + Number(stats?.skipped ?? 0) + Number(stats?.failed ?? 0);

/**
 * Rows still waiting. Before the first batch finishes the server has only said how many rows it
 * will apply (`to_apply`), so that is the fallback; afterwards its own `remaining` is exact.
 */
export function remainingOf(stats) {
  if (stats?.remaining != null) return Math.max(0, Number(stats.remaining));
  return Math.max(0, Number(stats?.to_apply ?? 0) - doneOf(stats));
}

/** Progress of a running import, 0-100. */
export function progressOf(stats) {
  const done = doneOf(stats);
  const all = done + remainingOf(stats);
  if (all <= 0) return 0;
  return Math.min(100, Math.round((done / all) * 100));
}

/** The most frequent problems first, as [{ code, text, count }]. */
export function topProblems(stats, limit = 5) {
  const counts = {};
  for (const s of Object.values(stats?.sheets ?? {}))
    for (const [code, n] of Object.entries(s?.error_codes ?? {})) counts[code] = (counts[code] ?? 0) + Number(n);
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([code, count]) => ({ code, text: errorText(code), count }));
}
