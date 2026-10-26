import { describe, expect, it } from "vitest";
import { shiftEmployees, shiftFromApi, shiftsFromApi, shiftsSummary } from "./shiftAdapter";

// The close RECORDS the day: closing balance = opening + invoices - returns, computed by the backend.
// Nothing is counted, so there is no counted figure, no shortage and no surplus anywhere.
const closedSession = {
  id: "s-1",
  register_id: "r-1",
  cashier_user_id: "u-1",
  status: "CLOSED",
  opened_at: "2026-10-20T09:00:00+00:00",
  closed_at: "2026-10-20T17:00:00+00:00",
  opening_float: "500.00",
  closing_balance: "19500.00",
};
const report = {
  opening_balance: "500.00",
  sales: { invoice_count: 20, total: "20000.00" },
  returns: { return_count: 1, total: "1000.00", documents: [{ receipt_id: "r1", receipt_number: "POS-RET-1", total: "1000.00", units: 1 }] },
  exchanges: { exchange_count: 1, difference_total: "50.00", documents: [{ receipt_id: "x1", receipt_number: "POS-RET-2", total: "100.00", new_total: "150.00", difference: "50.00", units: 1 }] },
  net_sales: "19000.00",
  closing_balance: "19500.00",
};

describe("shiftFromApi: the day is a record, not a count", () => {
  it("maps the user's own example: 500 + 20,000 - 1,000 = 19,500", () => {
    const row = shiftFromApi(closedSession, report);
    expect(row).toMatchObject({ status: "closed", openingCash: 500, invoices: 20, salesTotal: 20000, returnsTotal: 1000, closingBalance: 19500 });
  });

  it("lists the return and exchange invoices and the exchange value difference", () => {
    const row = shiftFromApi(closedSession, report);
    expect(row.returnDocs).toHaveLength(1);
    expect(row.exchangeDocs[0].difference).toBe("50.00");
    expect(row.exchangeDifference).toBe(50);
  });

  it("has no counted, expected, actual, variance or difference field any more", () => {
    const row = shiftFromApi(closedSession, report);
    for (const k of ["actual", "expected", "difference", "variance", "cashSales", "nonCashSales", "returnsCash", "expensesCash"]) {
      expect(row).not.toHaveProperty(k);
    }
  });

  it("an OPEN day takes its closing balance from the live report", () => {
    const row = shiftFromApi({ ...closedSession, status: "OPEN", closed_at: null, closing_balance: undefined }, report);
    expect(row.status).toBe("open");
    expect(row.closingBalance).toBe(19500);
    expect(row.closedAt).toBeNull();
  });

  it("a closed day with a stored closing balance trusts it over a missing report", () => {
    expect(shiftFromApi(closedSession, null).closingBalance).toBe(19500);
  });

  it("no report and nothing stored -> unknown (null), never a zero that looks real", () => {
    const row = shiftFromApi({ ...closedSession, status: "OPEN", closing_balance: undefined }, null);
    expect(row.closingBalance).toBeNull();
  });

  it("a day whose report failed to load has unknown figures, not zeros", () => {
    const row = shiftFromApi({ ...closedSession, closing_balance: undefined }, null);
    expect(row.reportLoaded).toBe(false);
    expect(row.invoices).toBeNull();
    expect(row.salesTotal).toBeNull();
    expect(row.returnsTotal).toBeNull();
    expect(row.closingBalance).toBeNull();
  });

  it("a day with a real report of nothing sold is a genuine zero", () => {
    const row = shiftFromApi(closedSession, { ...report, sales: { invoice_count: 0, total: "0.00" }, returns: { total: "0.00", documents: [] } });
    expect(row.reportLoaded).toBe(true);
    expect(row.invoices).toBe(0);
    expect(row.salesTotal).toBe(0);
  });

  it("an old closed day without a fetched report still shows its stored closing balance", () => {
    const row = shiftFromApi(closedSession, null);
    expect(row.closingBalance).toBe(19500); // stored on the session
    expect(row.reportLoaded).toBe(false);
    expect(row.salesTotal).toBeNull(); // unknown, not zero
  });

  it("the totals skip unknown days instead of counting them as zero", () => {
    const known = shiftFromApi(closedSession, report);
    const unknown = shiftFromApi({ ...closedSession, id: "x", closing_balance: undefined }, null);
    const s = shiftsSummary([known, unknown]);
    expect(s.salesTotal).toBe(20000);
    expect(s.unknownDays).toBe(1);
  });

  it("keeps cents exact (0.10 + 0.20 style sums do not drift)", () => {
    const row = shiftFromApi({ ...closedSession, closing_balance: "0.30" }, { ...report, sales: { invoice_count: 1, total: "0.30" } });
    expect(row.closingBalance).toBe(0.3);
    expect(row.salesTotal).toBe(0.3);
  });

  it("a malformed money string fails loudly instead of showing NaN", () => {
    expect(() => shiftFromApi({ ...closedSession, closing_balance: "abc" }, null)).toThrow();
  });
});

describe("shiftsFromApi", () => {
  it("sorts newest first", () => {
    const rows = shiftsFromApi([
      { ...closedSession, id: "old", opened_at: "2026-10-01T09:00:00Z" },
      { ...closedSession, id: "new", opened_at: "2026-10-20T09:00:00Z" },
    ]);
    expect(rows.map((r) => r.id)).toEqual(["new", "old"]);
  });
});

describe("shiftsSummary / shiftEmployees", () => {
  const rows = [
    { status: "open", employee: "منى", salesTotal: 100, returnsTotal: 0, closingBalance: 100 },
    { status: "closed", employee: "أحمد", salesTotal: 300, returnsTotal: 20, closingBalance: 280 },
    { status: "closed", employee: "منى", salesTotal: 200, returnsTotal: 0, closingBalance: 200 },
  ];
  it("totals sales and returns, and sums the closed days' ending balances", () => {
    const s = shiftsSummary(rows);
    expect(s.count).toBe(3);
    expect(s.closedCount).toBe(2);
    expect(s.open.employee).toBe("منى");
    expect(s.salesTotal).toBe(600);
    expect(s.returnsTotal).toBe(20);
    expect(s.closedBalance).toBe(480);
    expect(s).not.toHaveProperty("differences");
    expect(s).not.toHaveProperty("collected");
  });
  it("is safe on no shifts", () => {
    expect(shiftsSummary([])).toMatchObject({ open: null, count: 0, salesTotal: 0, returnsTotal: 0 });
  });
  it("lists each employee once, sorted", () => {
    expect(shiftEmployees(rows)).toEqual(["أحمد", "منى"]);
  });
});

describe("shiftsSummary: the running day", () => {
  const row = (id, employeeId, status = "open") => ({ id, employeeId, status, salesTotal: 0, returnsTotal: 0, closingBalance: 0 });

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
