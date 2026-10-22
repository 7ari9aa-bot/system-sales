import { describe, expect, it } from "vitest";
import { dayReportFigures } from "./DayReport";

describe("day report figures", () => {
  const sales = [
    { id: "a", total: 199.5, pieces: 1 },
    { id: "b", total: 350, pieces: 2 },
  ];

  it("counts the invoices, pieces and total of the day", () => {
    const f = dayReportFigures({ openingCash: 500, actual: 1050, status: "closed", closedAt: "2026-10-22T20:00:00Z" }, sales);
    expect(f).toMatchObject({ invoices: 2, pieces: 3, total: 549.5, opening: 500, counted: 1050, closed: true });
  });

  it("an open day has no counted drawer yet", () => {
    const f = dayReportFigures({ openingCash: 500, actual: null, status: "open" }, sales);
    expect(f.counted).toBeNull();
    expect(f.closed).toBe(false);
  });

  it("a day with no sales reports zero, not a crash", () => {
    expect(dayReportFigures({ openingCash: 0, status: "open" }, [])).toMatchObject({ invoices: 0, pieces: 0, total: 0 });
  });
});
