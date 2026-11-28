import { describe, expect, it } from "vitest";
import { costValue, daysValue, deadStockDays, deadStockRows, deadStockTotals } from "./deadStockReport";
import { shapeDeadStock } from "./useDeadStock";

describe("costValue: an unknown cost is null, never zero", () => {
  it("reads the server's money text exactly to the cent", () => {
    expect(costValue("50.00")).toBe(50);
    expect(costValue("12.50")).toBe(12.5);
    expect(costValue("10.01")).toBe(10.01);
  });
  it("null, undefined and blank stay null", () => {
    expect(costValue(null)).toBeNull();
    expect(costValue(undefined)).toBeNull();
    expect(costValue("")).toBeNull();
  });
  it("a real zero is a real zero", () => {
    expect(costValue("0.00")).toBe(0);
  });
});

describe("daysValue: never sold is null, sold today is 0", () => {
  it("separates the two", () => {
    expect(daysValue(null)).toBeNull();
    expect(daysValue(undefined)).toBeNull();
    expect(daysValue("")).toBeNull();
    expect(daysValue(0)).toBe(0);
    expect(daysValue(75)).toBe(75);
    expect(daysValue("abc")).toBeNull();
  });
});

describe("deadStockRows", () => {
  it("a value without the server's cost_known flag is not trusted as a known cost", () => {
    const [r] = deadStockRows([{ variant_id: "v", units_on_hand: 2, stock_value_at_cost: "50.00", cost_known: false }]);
    expect(r.costKnown).toBe(false);
  });
  it("the flag without a value is not a known cost either", () => {
    const [r] = deadStockRows([{ variant_id: "v", units_on_hand: 2, stock_value_at_cost: null, cost_known: true }]);
    expect(r.costKnown).toBe(false);
  });

  const known = {
    variant_id: "v1", model: "قميص", season: "SS26", material: "قطن", size: "M", colour: "أسود",
    units_on_hand: 4, last_sold_at: "2026-08-01T00:00:00+00:00", days_since_last_sale: 112,
    cost_known: true, unit_cost: "12.50", stock_value_at_cost: "50.00",
  };
  it("maps a row with a known cost", () => {
    expect(deadStockRows([known])[0]).toMatchObject({
      id: "v1", unitsOnHand: 4, daysSinceSale: 112, costKnown: true, unitCost: 12.5, value: 50, material: "قطن",
    });
  });
  it("an unknown cost keeps value and unit cost null and costKnown false", () => {
    const [r] = deadStockRows([{ ...known, cost_known: false, unit_cost: null, stock_value_at_cost: null }]);
    expect(r.costKnown).toBe(false);
    expect(r.value).toBeNull();
    expect(r.unitCost).toBeNull();
  });
  it("a row that says the cost is known but sends no figure is treated as unknown", () => {
    const [r] = deadStockRows([{ ...known, cost_known: true, stock_value_at_cost: null }]);
    expect(r.costKnown).toBe(false);
  });
  it("a size that never sold has no days and no date", () => {
    const [r] = deadStockRows([{ ...known, last_sold_at: null, days_since_last_sale: null }]);
    expect(r.daysSinceSale).toBeNull();
    expect(r.lastSoldAt).toBeNull();
  });
  it("copes with no rows", () => {
    expect(deadStockRows()).toEqual([]);
    expect(deadStockRows(null)).toEqual([]);
  });
});

describe("deadStockTotals", () => {
  it("maps the totals and takes the server's completeness flag", () => {
    expect(deadStockTotals({ variants: 2, units_on_hand: 9, stock_value_at_cost: "90.00", variants_without_cost: 1, cost_is_complete: false })).toEqual({
      variants: 2, unitsOnHand: 9, value: 90, withoutCost: 1, costIsComplete: false,
    });
  });
  it("a missing flag is NOT a promise that every cost is known", () => {
    expect(deadStockTotals({ variants: 1 }).costIsComplete).toBe(false);
    expect(deadStockTotals(undefined).costIsComplete).toBe(false);
  });
  it("only an explicit true counts as complete", () => {
    expect(deadStockTotals({ cost_is_complete: true }).costIsComplete).toBe(true);
    expect(deadStockTotals({ cost_is_complete: "true" }).costIsComplete).toBe(false);
  });
});

describe("deadStockDays and shapeDeadStock", () => {
  it("reads the window the server used", () => {
    expect(deadStockDays({ days: 60 })).toBe(60);
    expect(deadStockDays({ days: 0 })).toBeNull();
    expect(deadStockDays({})).toBeNull();
    expect(deadStockDays(undefined)).toBeNull();
  });
  it("shapes the whole answer", () => {
    const out = shapeDeadStock({ days: 30, rows: [{ variant_id: "v" }], totals: { variants: 1 } });
    expect(out.days).toBe(30);
    expect(out.rows).toHaveLength(1);
    expect(out.totals.variants).toBe(1);
  });
  it("an empty answer is an empty table", () => {
    const out = shapeDeadStock(undefined);
    expect(out.days).toBeNull();
    expect(out.rows).toEqual([]);
  });
});
