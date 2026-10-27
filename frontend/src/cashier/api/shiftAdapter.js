/**
 * Backend POS session -> the row shape the Shifts screens already render.
 *
 * Rule: the backend owns the numbers. The day's closing balance (opening + invoices - returns) comes
 * from the ledger on the server; nothing is counted and there is no shortage or surplus, so they are mapped as-is and never recomputed here (the old mock
 * rows computed expected = opening + cashSales - returns - expenses on the client, which
 * ignores pay-ins/pay-outs). Numbers are produced only for display, via integer minor units.
 */
import { parseMoney } from "./money";

const num = (wire, fallback = 0) => {
  if (wire === null || wire === undefined || wire === "") return fallback;
  const { minor } = parseMoney(wire); // throws on malformed input instead of showing NaN
  return minor / 100;
};

export function shiftFromApi(session, report = null, { employees = {} } = {}) {
  const closed = session.status === "CLOSED";
  // Closing balance = opening + invoices - returns, computed by the backend. Open day: from the live
  // report; closed day: stored on the session. Neither -> null (unknown), never a zero that looks real.
  const closing =
    closed && session.closing_balance != null
      ? num(session.closing_balance)
      : report?.closing_balance != null
        ? num(report.closing_balance)
        : null;
  const known = report != null; // the day's report loaded: its invoices/returns are real figures
  return {
    id: session.id,
    number: `SH-${String(session.id).slice(0, 8).toUpperCase()}`,
    date: session.opened_at,
    closedAt: closed ? session.closed_at : null,
    status: closed ? "closed" : "open",
    registerId: session.register_id,
    // A day started without a shift has no holder: the person who started it is the employee.
    employeeId: session.cashier_user_id ?? session.opened_by_user_id ?? null,
    employee: employees[session.cashier_user_id ?? session.opened_by_user_id] ?? "موظف غير معروف",
    branch: "",
    openingCash: num(session.opening_float),
    reportLoaded: known,
    invoices: known ? (report.sales?.invoice_count ?? 0) : null,
    pieces: 0,
    note: "",
    salesTotal: known ? num(report.sales?.total) : null,
    returnsTotal: known ? num(report.returns?.total) : null,
    returnDocs: report?.returns?.documents ?? [],
    exchangeDocs: report?.exchanges?.documents ?? [],
    exchangeDifference: num(report?.exchanges?.difference_total),
    closingBalance: closing,
  };
}

export function shiftsFromApi(sessions, reports = {}, opts = {}) {
  return [...(sessions ?? [])]
    .sort((a, b) => String(b.opened_at).localeCompare(String(a.opened_at)))
    .map((s) => shiftFromApi(s, reports[s.id] ?? null, opts));
}

/** A line for the summary cards when some days' figures are not in the totals; "" when all are. */
export function coverageNote({ unknownDays = 0 } = {}) {
  return unknownDays > 0 ? `${unknownDays} يوم أقدم غير محسوب في الإجمالي` : "";
}

/** Totals for the shifts screen, computed from the real rows. `open` is the drawer that is still running. */
export function shiftsSummary(rows = []) {
  // `open` is the day that is running. The day belongs to the register, not to a person: it is opened
  // with the drawer's balance (`open-day`) and carries no cashier, so it is never looked up by user.
  // With several registers the first open day is shown; each register has at most one.
  const openRows = rows.filter((r) => r.status === "open");
  const open = openRows[0] ?? null;
  const closed = rows.filter((r) => r.status === "closed");
  return {
    open,
    othersOpen: openRows.length > 1 ? openRows.length - 1 : 0,
    count: rows.length,
    closedCount: closed.length,
    unknownDays: rows.filter((r) => r.reportLoaded === false).length,
    salesTotal: +rows.reduce((s, r) => s + (r.salesTotal ?? 0), 0).toFixed(2),
    returnsTotal: +rows.reduce((s, r) => s + (r.returnsTotal ?? 0), 0).toFixed(2),
    // What the closed days ended on: opening + invoices - returns, summed. Not a count of anything.
    closedBalance: +closed.reduce((s, r) => s + (r.closingBalance ?? 0), 0).toFixed(2),
  };
}

/** The distinct employees who actually worked a shift, for the filter. */
export function shiftEmployees(rows = []) {
  // One entry per employee ID: two people we cannot name stay two entries, never one "cashier".
  const byId = new Map();
  for (const r of rows) if (r.employeeId && !byId.has(r.employeeId)) byId.set(r.employeeId, r.employee);
  return [...byId].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, "ar"));
}

/** id -> name for every member we can see plus the signed-in user (members may be hidden from a cashier). */
export function employeeMap(members = [], me = null) {
  const out = {};
  for (const m of members ?? []) if (m?.id) out[m.id] = m.name;
  if (me?.id) out[me.id] = me.name;
  return out;
}
