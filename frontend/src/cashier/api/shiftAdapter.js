/**
 * Backend POS session -> the row shape the Shifts screens already render.
 *
 * Rule: the backend owns the money. `expected_cash`, `counted_cash` and `variance` come from
 * the ledger on the server, so they are mapped as-is and never recomputed here (the old mock
 * rows computed expected = opening + cashSales - returns - expenses on the client, which
 * ignores pay-ins/pay-outs). Numbers are produced only for display, via integer minor units.
 */
import { parseMoney } from "./money";

const num = (wire, fallback = 0) => {
  if (wire === null || wire === undefined || wire === "") return fallback;
  const { minor } = parseMoney(wire); // throws on malformed input instead of showing NaN
  return minor / 100;
};

const byMethod = (report, method, field = "expected") => {
  const hit = report?.by_method?.find((m) => m.method === method);
  return hit ? num(hit[field]) : 0;
};

export function shiftFromApi(session, report = null, { employees = {} } = {}) {
  const closed = session.status === "CLOSED";
  const expected = num(session.expected_cash);
  const actual = closed ? num(session.counted_cash) : null;
  return {
    id: session.id,
    number: `SH-${String(session.id).slice(0, 8).toUpperCase()}`,
    date: session.opened_at,
    closedAt: closed ? session.closed_at : null,
    status: closed ? "closed" : "open",
    registerId: session.register_id,
    employeeId: session.cashier_user_id,
    employee: employees[session.cashier_user_id] ?? "كاشير",
    branch: "",
    openingCash: num(session.opening_float),
    invoices: report?.sales?.invoice_count ?? 0,
    pieces: 0,
    cashSales: num(report?.cash_in),
    cardSales: byMethod(report, "card"),
    walletSales: byMethod(report, "wallet"),
    creditSales: byMethod(report, "credit"),
    returnsCash: num(report?.returns?.total),
    expensesCash: num(report?.cash_out),
    variance: closed ? num(session.variance) : 0,
    note: "",
    otherSales: byMethod(report, "card") + byMethod(report, "wallet") + byMethod(report, "credit"),
    expected,
    actual,
    difference: closed ? num(session.variance) : 0,
  };
}

export function shiftsFromApi(sessions, reports = {}, opts = {}) {
  return [...(sessions ?? [])]
    .sort((a, b) => String(b.opened_at).localeCompare(String(a.opened_at)))
    .map((s) => shiftFromApi(s, reports[s.id] ?? null, opts));
}
