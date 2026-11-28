import { describe, expect, it } from "vitest";
import { shiftEmployees, shiftFromApi, shiftsFromApi, shiftsSummary, employeeMap, closeSummary, coverageNote, nameEmployees } from "./shiftAdapter";

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

  it("coverageNote tells the owner when the totals leave days out", () => {
    expect(coverageNote({ unknownDays: 0 })).toBe("");
    expect(coverageNote({ unknownDays: 3 })).toContain("3");
    expect(coverageNote({ unknownDays: 3 })).toContain("غير محسوب");
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
    { status: "open", employeeId: "u-mona", employee: "منى", salesTotal: 100, returnsTotal: 0, closingBalance: 100 },
    { status: "closed", employeeId: "u-ahmed", employee: "أحمد", salesTotal: 300, returnsTotal: 20, closingBalance: 280 },
    { status: "closed", employeeId: "u-mona", employee: "منى", salesTotal: 200, returnsTotal: 0, closingBalance: 200 },
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
    expect(shiftEmployees(rows)).toEqual([{ id: "u-ahmed", name: "أحمد" }, { id: "u-mona", name: "منى" }]);
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

describe("employees by id", () => {
  const A = { ...closedSession, id: "a", cashier_user_id: "u1", opened_by_user_id: "u1" };
  const B = { ...closedSession, id: "b", cashier_user_id: null, opened_by_user_id: "u2" };
  const C = { ...closedSession, id: "c", cashier_user_id: null, opened_by_user_id: "u3" };

  it("names each day's employee from its own id, not a single shared label", () => {
    const rows = shiftsFromApi([A, B], {}, { employees: { u1: "منى", u2: "علي" } });
    expect(rows.map((r) => r.employee).sort()).toEqual(["علي", "منى"]);
    expect(rows.find((r) => r.id === "b").employeeId).toBe("u2"); // opened_by is used when there is no holder
  });

  it("an employee we cannot name is 'unknown', and two unknowns stay separate by id", () => {
    const rows = shiftsFromApi([B, C], {}, { employees: {} });
    expect(rows[0].employee).not.toBe("كاشير");
    const list = shiftEmployees(rows);
    expect(list.map((e) => e.id).sort()).toEqual(["u2", "u3"]);
  });

  it("employeeMap turns the shop's members into an id -> name dictionary", () => {
    expect(employeeMap([{ id: "u1", name: "منى" }, { id: "u2", name: "علي" }], { id: "u9", name: "أنا" })).toEqual({ u1: "منى", u2: "علي", u9: "أنا" });
    expect(employeeMap(undefined, null)).toEqual({});
  });
});

describe("closeSummary: what the close toast and the report take from the server's answer", () => {
  it("keeps an absent closing balance unknown instead of inventing zero", () => {
    expect(closeSummary({ closed_at: "2026-10-26T20:00:00Z" }, { closingBalance: null }).closingBalance).toBeNull();
    expect(closeSummary(undefined, { closingBalance: null }).closingBalance).toBeNull();
  });
  it("uses the server's balance, else the one the row already had", () => {
    expect(closeSummary({ closing_balance: "19500.00" }, { closingBalance: 1 }).closingBalance).toBe(19500);
    expect(closeSummary({}, { closingBalance: 480 }).closingBalance).toBe(480);
  });
});

describe("coverageNote names the cause", () => {
  it("separates days with no report loaded from simply old days", () => {
    expect(coverageNote({ unknownDays: 2 })).toContain("2");
    expect(coverageNote({ unknownDays: 2 })).not.toContain("أقدم");
  });
});

describe("nameEmployees: names are applied after the rows load, so a late member list still names them", () => {
  const rows = shiftsFromApi([{ ...closedSession, id: "b", cashier_user_id: null, opened_by_user_id: "u2" }], {}, { employees: {} });

  it("rows loaded before the names arrive show 'unknown', then the real name once they do", () => {
    expect(rows[0].employee).toBe("موظف غير معروف");
    expect(nameEmployees(rows, { u2: "علي" })[0].employee).toBe("علي");
  });
  it("leaves a name it cannot resolve as it was, and does not mutate the input", () => {
    const out = nameEmployees(rows, {});
    expect(out[0].employee).toBe("موظف غير معروف");
    expect(nameEmployees(rows, { u2: "علي" })).not.toBe(rows);
    expect(rows[0].employee).toBe("موظف غير معروف");
  });
});
