import { describe, expect, test } from "vitest";
import { scalarPairs } from "./AnalyticsPanels";

describe("scalarPairs", () => {
  test("renders only the scalars a read model returned, humanised", () => {
    const pairs = scalarPairs({ gross_revenue: 1200, order_count: 4, currency: "EGP" });
    expect(pairs).toEqual([
      ["Gross Revenue", "1,200"],
      ["Order Count", "4"],
      ["Currency", "EGP"],
    ]);
  });

  test("drops nested collections instead of stringifying them into the page", () => {
    const pairs = scalarPairs({ total: 5, series: [1, 2, 3], breakdown: { a: 1 } });
    expect(pairs).toEqual([["Total", "5"]]);
  });

  test("booleans and missing values read as a person would write them", () => {
    expect(scalarPairs({ live: true, closed: false, note: null })).toEqual([
      ["Live", "✓"],
      ["Closed", "✗"],
      ["Note", "—"],
    ]);
  });

  test("a non-object answer never throws", () => {
    expect(scalarPairs(null)).toEqual([]);
    expect(scalarPairs("nope")).toEqual([]);
  });
});
