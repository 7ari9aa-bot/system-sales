/**
 * Pure helpers for the e-receipt tracking screen: what the backend says about each receipt, said
 * the way a shop owner would say it.
 *
 * The backend (backend/app/modules/einvoice/tracking.py) decides how much a receipt needs the
 * owner: ok | retrying | fix | urgent | expired. This file only words it. The deadline rule
 * (96 hours to replace a refused receipt, 72 for a return with no reference) lives on the server,
 * so the screen can never disagree with the sender about when time runs out.
 */

/** The order the owner reads: the one closest to its deadline first. Mirrors the backend's sort. */
export const ATTENTION_ORDER = ["expired", "urgent", "fix", "retrying", "ok"];

/** The filter the list offers. The values are exactly the groups the backend accepts. */
export const GROUPS = [
  { value: "", label: "الكل" },
  { value: "rejected", label: "مرفوضة" },
  { value: "retrying", label: "بتتعاد" },
  { value: "waiting", label: "في الانتظار" },
  { value: "accepted", label: "مقبولة" },
  { value: "cancelled", label: "ملغاة" },
];

const STATUS_AR = {
  draft: "مسودة",
  signed: "جاهزة للإرسال",
  submitted: "اتبعتت للمصلحة",
  cleared: "قبلتها المصلحة",
  reported: "قبلتها المصلحة",
  rejected: "رفضتها المصلحة",
  failed: "الإرسال فشل وبيتعاد",
  cancelled: "ملغاة",
};

const ATTENTION_AR = {
  ok: "",
  retrying: "النظام بيعيد الإرسال لوحده",
  fix: "مرفوضة وتحتاج تصحيح",
  urgent: "مرفوضة والمهلة قربت تخلص",
  expired: "المهلة انتهت: لازم طلب تقديم متأخر من بوابة المصلحة",
};

export function statusLabel(status) {
  return STATUS_AR[status] ?? String(status ?? "");
}

export function attentionLabel(level) {
  return ATTENTION_AR[level] ?? "";
}

/** "3 أيام و14 ساعة": the time left to replace a refused receipt, in whole units. */
export function hoursLeftText(hours) {
  if (hours === null || hours === undefined || Number.isNaN(Number(hours))) return "";
  const h = Number(hours);
  if (h <= 0) return "انتهت المهلة";
  if (h < 1) return "أقل من ساعة";
  const total = Math.floor(h);
  const days = Math.floor(total / 24);
  const rest = total % 24;
  const d = days === 0 ? "" : days === 1 ? (rest === 0 ? "يوم واحد" : "يوم") : days === 2 ? "يومان" : days <= 10 ? `${days} أيام` : `${days} يومًا`;
  const hr = rest === 0 ? "" : rest === 1 ? "ساعة واحدة" : rest === 2 ? "ساعتان" : rest <= 10 ? `${rest} ساعات` : `${rest} ساعة`;
  return [d, hr].filter(Boolean).join(" و");
}

/** Backend receipt -> the row the table renders. */
export function receiptFromApi(r) {
  return {
    id: String(r.id),
    number: r.invoice_number,
    type: r.document_type,
    status: r.status,
    statusText: statusLabel(r.status),
    attention: r.attention ?? "ok",
    attentionText: attentionLabel(r.attention),
    hoursLeft: r.hours_left ?? null,
    deadlineText: hoursLeftText(r.hours_left),
    errors: Array.isArray(r.errors) ? r.errors : [],
    attempts: r.attempts ?? 0,
    nextAttemptAt: r.next_attempt_at ?? null,
    issuedAt: r.issued_at,
    orderId: r.order_id ?? null,
    authorityUuid: r.authority_uuid ?? null,
  };
}

const n = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);

/** The counters at the top. What needs the owner comes first; a calm shop sees a calm card. */
export function summaryCards(s) {
  const needs = n(s?.needs_attention);
  const urgent = n(s?.urgent);
  return [
    { key: "needs_attention", label: "محتاجة تصرف منك", value: needs, tone: needs > 0 ? "danger" : "ok" },
    { key: "urgent", label: "المهلة قربت تخلص", value: urgent, tone: urgent > 0 ? "danger" : "muted" },
    { key: "accepted", label: "مقبولة", value: n(s?.accepted), tone: "ok" },
    { key: "waiting", label: "في الانتظار", value: n(s?.waiting), tone: "muted" },
    { key: "retrying", label: "بتتعاد", value: n(s?.retrying), tone: "muted" },
  ];
}

const KNOWN_GROUPS = new Set(GROUPS.map((g) => g.value).filter(Boolean));

/** The query string for the list. Only what was chosen goes out, and a group the server would refuse never does. */
export function groupQuery({ group = "", from = "", to = "", limit, offset } = {}) {
  const p = new URLSearchParams();
  if (KNOWN_GROUPS.has(group)) p.set("group", group);
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  if (limit) p.set("limit", String(limit));
  if (offset) p.set("offset", String(offset));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function trackingErrorMessage(err) {
  if (err?.status === 403) return "ما عندكش صلاحية تشوف متابعة الإيصالات. اطلب من صاحب المحل.";
  return "ما قدرناش نجيب الإيصالات دلوقتي. جرّب تاني بعد شوية.";
}
