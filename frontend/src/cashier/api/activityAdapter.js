/**
 * Operations log: backend timeline event -> the row the table renders. Pure, so it is unit-tested.
 *
 * The backend sends MACHINE values in `detail` for a few kinds (a movement reason, a shift verb)
 * and keeps the customer's own text (item names, supplier, expense description) as is; this file
 * is the only place that turns the machine values into Arabic.
 */
import { fromMinor, toMinor } from "./money";

export const ACTIVITY_PAGE = 200;

const MOVEMENT_REASONS = {
  sale: "بيع",
  return: "مرتجع عميل",
  purchase: "توريد",
  adjustment: "تسوية جرد",
  supplier_return: "مرتجع لمورد",
  supplier_return_reversal: "رجوع مرتجع مورد للرف",
  transfer: "تحويل",
};
const DIRECTIONS = { in: "دخول", out: "خروج" };
const RETURN_STATUS = { pending: "قيد المراجعة", accepted: "مقبول", rejected: "مرفوض" };

/** "supplier_return / out" -> "مرتجع لمورد • خروج". An unknown reason stays visible, never blank. */
export function movementDetail(raw) {
  const [reason = "", direction = ""] = String(raw ?? "").split(" / ");
  const why = MOVEMENT_REASONS[reason] ?? reason;
  const dir = DIRECTIONS[direction] ?? direction;
  return [why, dir].filter(Boolean).join(" • ");
}

/** "opened" / "closed variance=-3.00" -> Arabic, with the variance only when there is one. */
export function shiftDetail(raw) {
  const text = String(raw ?? "");
  if (text === "opened") return "تم فتح الوردية";
  const m = text.match(/^closed variance=(-?\d+(?:\.\d+)?)$/);
  if (!m) return text;
  const minor = toMinor(m[1]);
  if (minor === 0) return "تم إغلاق الوردية بدون عجز أو زيادة";
  return minor < 0
    ? `تم إغلاق الوردية • عجز ${fromMinor(-minor)}`
    : `تم إغلاق الوردية • زيادة ${fromMinor(minor)}`;
}

/** "مورد س · accepted" -> "مورد س • مقبول". */
export function supplierReturnDetail(raw) {
  const text = String(raw ?? "");
  const at = text.lastIndexOf(" · ");
  if (at < 0) return text;
  const status = text.slice(at + 3);
  return `${text.slice(0, at)} • ${RETURN_STATUS[status] ?? status}`;
}

function detailFor(e) {
  switch (e.kind) {
    case "inventory":
      return movementDetail(e.detail);
    case "shift":
      return shiftDetail(e.detail);
    case "supplier_return":
      return supplierReturnDetail(e.detail);
    default:
      return e.detail ?? "";
  }
}

export function activityFromApi(e) {
  return {
    id: e.event_key ?? `${e.kind}:${e.ref_id}:${e.doc}`,
    type: e.kind,
    date: e.occurred_at,
    doc: e.doc,
    details: detailFor(e),
    // Inventory carries a unit count, every other kind carries money.
    amount: e.kind === "inventory" ? null : e.amount,
    quantity: e.kind === "inventory" ? Number(e.amount) : null,
    employee: e.actor_name ?? "",
    employeeId: e.actor_id ?? null,
  };
}

export function activityPageFromApi(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return { rows: items.map(activityFromApi), next: payload?.next_cursor ?? null };
}

/** Screen filters -> the query string. An empty filter is simply left out. */
export function activityQuery({ term = "", type = "", employeeId = "", from = "", to = "", cursor = "" } = {}) {
  const p = new URLSearchParams({ limit: String(ACTIVITY_PAGE) });
  const t = term.trim();
  if (t) p.set("q", t);
  if (type) p.set("kinds", type);
  if (employeeId) p.set("actor_id", employeeId);
  if (from) p.set("date_from", from);
  if (to) p.set("date_to", to);
  if (cursor) p.set("cursor", cursor);
  return p.toString();
}

/** Employees seen in the loaded rows, as {id, name}, sorted by Arabic name. Rows with no actor are skipped. */
export function employeesIn(rows) {
  const seen = new Map();
  for (const r of rows) if (r.employeeId && r.employee) seen.set(r.employeeId, r.employee);
  return [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, "ar"));
}
