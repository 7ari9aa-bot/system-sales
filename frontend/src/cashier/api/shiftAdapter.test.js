import { describe, expect, it } from "vitest";
import { shiftFromApi, shiftsFromApi } from "./shiftAdapter";

const session = {
  id: "s-1",
  register_id: "r-1",
  cashier_user_id: "u-1",
  status: "CLOSED",
  opened_at: "2026-10-20T09:00:00+00:00",
  closed_at: "2026-10-20T17:00:00+00:00",
  opening_float: "100.00",
  expected_cash: "120.00",
  counted_cash: "118.00",
  variance: "-2.00",
};
const report = {
  opening_float: "100.00",
  cash_in: "30.00",
  cash_out: "10.00",
  cash_movements: [
    { direction: "in", reason: "cash_sale", amount: "30.00" },
    { direction: "out", reason: "cash_refund", amount: "5.00" },
    { direction: "out", reason: "pay_out", amount: "5.00" },
  ],
  sales: { invoice_count: 1, total: "50.00" },
  returns: { return_count: 1, total: "5.00" },
  by_method: [
    { method: "card", expected: "20.00", counted: "20.00", variance: "0.00" },
    { method: "cash", expected: "120.00", counted: "118.00", variance: "-2.00" },
    { method: "wallet", expected: "7.50", counted: "7.50", variance: "0.00" },
  ],
};

describe("shiftFromApi", () => {
  it("maps a closed shift and TRUSTS the backend's expected/variance instead of recomputing", () => {
    const row = shiftFromApi(session, report, { employees: { "u-1": "منى" } });
    expect(row).toMatchObject({
      id: "s-1",
      status: "closed",
      employee: "منى",
      openingCash: 100,
      expected: 120,
      actual: 118,
      difference: -2,
      nonCashSales: 27.5, // old card 20 + wallet 7.5 are kept, as ONE figure
      invoices: 1,
    });
  });

  it("an open shift has no actual count and no difference yet", () => {
    const row = shiftFromApi({ ...session, status: "OPEN", closed_at: null, counted_cash: null, variance: null });
    expect(row.status).toBe("open");
    expect(row.actual).toBeNull();
    expect(row.difference).toBe(0);
    expect(row.closedAt).toBeNull();
  });

  it("a shortage stays a shortage: the sign is never lost or flipped", () => {
    expect(shiftFromApi(session).difference).toBe(-2);
    expect(shiftFromApi({ ...session, variance: "3.50", counted_cash: "123.50" }).difference).toBe(3.5);
  });

  it("amounts keep cent precision (no 0.1 + 0.2 drift)", () => {
    const row = shiftFromApi({ ...session, opening_float: "0.10", expected_cash: "0.30", counted_cash: "0.30", variance: "0.00" });
    expect(row.openingCash).toBe(0.1);
    expect(row.expected).toBe(0.3);
  });

  it("falls back to a readable label when the employee name is unknown", () => {
    expect(shiftFromApi(session).employee).toMatch(/\S/);
  });

  it("without a report the per-method sales are zero, never undefined/NaN", () => {
    const row = shiftFromApi(session);
    for (const k of ["nonCashSales", "cashSales", "returnsCash", "expensesCash", "invoices", "pieces"]) {
      expect(Number.isFinite(row[k])).toBe(true);
    }
  });

  it("rejects a malformed amount instead of showing NaN", () => {
    expect(() => shiftFromApi({ ...session, opening_float: "abc" })).toThrow();
  });
});

describe("shiftsFromApi", () => {
  it("newest first and tolerant of an empty list", () => {
    const older = { ...session, id: "s-0", opened_at: "2026-10-19T09:00:00+00:00" };
    expect(shiftsFromApi([older, session]).map((r) => r.id)).toEqual(["s-1", "s-0"]);
    expect(shiftsFromApi([])).toEqual([]);
    expect(shiftsFromApi(null)).toEqual([]);
  });
});

describe("Z-report cash columns (real shift: card refund + exchange echo)", () => {
  // Numbers copied from a real backend shift: 6 sales (1650), 3 returns (590) of which 350 went back
  // on a CARD, and cash_in holds 940 of cash plus the 240 echo of an exchange.
  const real = {
    opening_float: "0.00",
    cash_in: "1180.00",
    cash_out: "240.00",
    sales: { invoice_count: 6, total: "1650.00" },
    returns: { return_count: 3, total: "590.00" },
    by_method: [
      { method: "card", expected: "120.00" },
      { method: "cash", expected: "940.00" },
    ],
    cash_movements: [
      { direction: "in", reason: "cash_sale", amount: "240.00" },
      { direction: "in", reason: "cash_sale", amount: "700.00" },
      { direction: "in", reason: "cash_sale", amount: "240.00" },
      { direction: "out", reason: "cash_refund", amount: "120.00" },
      { direction: "out", reason: "cash_refund", amount: "120.00" },
    ],
  };
  it("cash returns = cash that left the drawer, NOT the 590 refunded on every tender", () => {
    const row = shiftFromApi({ ...session, id: "s-2" }, real);
    expect(row.returnsCash).toBe(240);
    expect(row.returnsCash).not.toBe(590);
  });
  it("cash sales come from cash_sale movements; manual pay_out goes to the outflow column", () => {
    const row = shiftFromApi(session, { ...real, cash_movements: [...real.cash_movements, { direction: "out", reason: "pay_out", amount: "15.50" }] });
    expect(row.cashSales).toBe(1180);
    expect(row.expensesCash).toBe(15.5);
  });
  it("a refund is never counted as an expense, and a missing movements list is zero", () => {
    expect(shiftFromApi(session, { ...real, cash_movements: undefined }).returnsCash).toBe(0);
    expect(shiftFromApi(session, real).expensesCash).toBe(0);
  });
});

describe("expected cash of an OPEN shift", () => {
  const open = { id: "aaaaaaaa-1", status: "OPEN", opened_at: "2026-10-20T09:00:00Z", opening_float: "100.00", cashier_user_id: "u" };
  it("is derived from the report: opening + cash in - cash out", () => {
    const report = { opening_float: "100.00", cash_in: "450.00", cash_out: "120.00", sales: { invoice_count: 1 }, by_method: [], cash_movements: [] };
    expect(shiftFromApi(open, report).expected).toBe(430);
  });
  it("prefers the backend figure whenever it sends one", () => {
    expect(shiftFromApi({ ...open, expected_cash: "999.00" }, { opening_float: "1", cash_in: "1", cash_out: "0" }).expected).toBe(999);
  });
  it("is 0 (not a guess) when there is no report yet", () => {
    expect(shiftFromApi(open, null).expected).toBe(0);
  });
});

describe("payment methods are no longer modelled, but no historical money disappears", () => {
  const closed = { id: "bbbbbbbb-1", status: "CLOSED", opened_at: "2026-10-01T09:00:00Z", opening_float: "0.00", expected_cash: "0.00", counted_cash: "0.00", variance: "0.00", cashier_user_id: "u" };
  it("sums every non-cash method from the backend into one figure", () => {
    const report = { by_method: [{ method: "cash", expected: "100.00" }, { method: "card", expected: "20.00" }, { method: "wallet", expected: "7.50" }, { method: "credit", expected: "2.50" }], cash_movements: [] };
    expect(shiftFromApi(closed, report).nonCashSales).toBe(30);
  });
  it("is 0 when the shift was all cash", () => {
    expect(shiftFromApi(closed, { by_method: [{ method: "cash", expected: "100.00" }], cash_movements: [] }).nonCashSales).toBe(0);
  });
  it("does not expose the per-method fields any more", () => {
    const row = shiftFromApi(closed, { by_method: [], cash_movements: [] });
    for (const k of ["cardSales", "walletSales", "creditSales", "otherSales"]) expect(row).not.toHaveProperty(k);
  });
});

import { shiftEmployees as _shiftEmployees, shiftsSummary as _shiftsSummary } from "./shiftAdapter";
const shiftsSummary = _shiftsSummary;

describe("shiftsSummary / shiftEmployees", () => {
  const rows = [
    { status: "open", employee: "منى", cashSales: 100, difference: 0, actual: 0 },
    { status: "closed", employee: "أحمد", cashSales: 300, difference: -5, actual: 295 },
    { status: "closed", employee: "منى", cashSales: 200, difference: 2.5, actual: 202.5 },
  ];
  it("totals only closed shifts for differences and collected", () => {
    const s = _shiftsSummary(rows);
    expect(s.count).toBe(3);
    expect(s.closedCount).toBe(2);
    expect(s.open.employee).toBe("منى");
    expect(s.cashSales).toBe(600);
    expect(s.differences).toBe(7.5);
    expect(s.collected).toBe(497.5);
  });
  it("is safe on no shifts", () => {
    expect(_shiftsSummary([])).toMatchObject({ open: null, count: 0, cashSales: 0 });
  });
  it("lists each employee once, sorted", () => {
    expect(_shiftEmployees(rows)).toEqual(["أحمد", "منى"]);
  });
});

describe("shiftsSummary: the running day", () => {
  const row = (id, employeeId, status = "open") => ({ id, employeeId, status, cashSales: 0, difference: 0, actual: 0 });

  it("the open day is found even though it carries no cashier (open-day sets none)", () => {
    const s = shiftsSummary([row("day", null)]);
    expect(s.open.id).toBe("day");
    expect(s.othersOpen).toBe(0);
  });
  it("closed days never count as the running one", () => {
    expect(shiftsSummary([row("old", null, "closed")]).open).toBeNull();
  });
  it("with several registers each running a day, the first is shown and the rest are counted", () => {
    const s = shiftsSummary([row("a", null), row("b", null), row("c", null, "closed")]);
    expect(s.open.id).toBe("a");
    expect(s.othersOpen).toBe(1);
  });
});
