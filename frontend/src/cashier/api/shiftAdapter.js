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

// Cash that really moved through the drawer, by the backend's own reason. `report.returns.total` is
// every refund on every tender (a card refund never touches the drawer) and `cash_in` also holds the
// internal echo of an exchange, so neither is the "cash sales" / "cash returns" a Z report must show.
const cashBy = (report, direction, reasons) =>
  (report?.cash_movements ?? [])
    .filter((m) => m.direction === direction && reasons.includes(m.reason))
    .reduce((minor, m) => minor + parseMoney(m.amount).minor, 0) / 100;

export const CASH_SALE = ["cash_sale"];
export const CASH_REFUND = ["cash_refund"];
export const CASH_OTHER_OUT = ["pay_out", "cash_drop"];

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
    cashSales: cashBy(report, "in", CASH_SALE),
    cardSales: byMethod(report, "card"),
    walletSales: byMethod(report, "wallet"),
    creditSales: byMethod(report, "credit"),
    returnsCash: cashBy(report, "out", CASH_REFUND),
    expensesCash: cashBy(report, "out", CASH_OTHER_OUT),
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
