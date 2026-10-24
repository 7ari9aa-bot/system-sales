import { describe, expect, it } from "vitest";
import { dayReportFigures } from "./DayReport";

describe("day report figures: opening + invoices - returns", () => {
  const sales = [
    { id: "a", total: 199.5, pieces: 1 },
    { id: "b", total: 350, pieces: 2 },
  ];

  it("counts the invoices, pieces and total of the day, and takes the closing balance from the backend", () => {
    const f = dayReportFigures({ openingCash: 500, returnsTotal: 0, closingBalance: 1049.5, status: "closed", closedAt: "2026-10-22T20:00:00Z" }, sales);
    expect(f).toMatchObject({ invoices: 2, pieces: 3, total: 549.5, opening: 500, returns: 0, closing: 1049.5, closed: true });
  });

  it("the user's example: opens with 500, sells 20,000, takes back 1,000 -> ends on 19,500", () => {
    const f = dayReportFigures({ openingCash: 500, returnsTotal: 1000, closingBalance: 19500, status: "open" }, [{ id: "all", total: 20000, pieces: 20 }]);
    expect(f).toMatchObject({ opening: 500, total: 20000, returns: 1000, closing: 19500 });
  });

  it("falls back to opening + invoices - returns when the backend figure is missing", () => {
    const f = dayReportFigures({ openingCash: 500, returnsTotal: 100, status: "open" }, sales);
    expect(f.closing).toBe(949.5);
  });

  it("carries the return and exchange invoices for the lists", () => {
    const f = dayReportFigures({ openingCash: 0, returnDocs: [{ receipt_id: "r" }], exchangeDocs: [{ receipt_id: "x" }], exchangeDifference: 50, status: "open" }, []);
    expect(f.returnDocs).toHaveLength(1);
    expect(f.exchangeDocs).toHaveLength(1);
    expect(f.exchangeDifference).toBe(50);
  });

  it("has no counted drawer figure any more", () => {
    expect(dayReportFigures({ openingCash: 500, status: "closed" }, sales)).not.toHaveProperty("counted");
  });

  it("a day with no sales reports zero, not a crash", () => {
    expect(dayReportFigures({ openingCash: 0, status: "open" }, [])).toMatchObject({ invoices: 0, pieces: 0, total: 0, returns: 0 });
  });
});
