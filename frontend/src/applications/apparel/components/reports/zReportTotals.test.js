import { describe, expect, it } from "vitest";
import { zReportTotals } from "./zReportTotals";

const day = (closing) => ({ invoices: 2, salesTotal: 50, returnsTotal: 10, exchangeDifference: 5, closingBalance: closing });

describe("zReportTotals", () => {
  it("adds up movement across days", () => {
    expect(zReportTotals([day(150), day(150)])).toEqual({ invoices: 4, salesTotal: 100, returnsTotal: 20, exchangeDifference: 10 });
  });
  it("has no closing-balance total: summing different days' balances means nothing", () => {
    expect(zReportTotals([day(150), day(150)])).not.toHaveProperty("closingBalance");
  });
});
