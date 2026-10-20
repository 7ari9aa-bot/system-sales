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
      cardSales: 20,
      walletSales: 7.5,
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
    for (const k of ["cardSales", "walletSales", "creditSales", "cashSales", "returnsCash", "expensesCash", "invoices", "pieces"]) {
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
