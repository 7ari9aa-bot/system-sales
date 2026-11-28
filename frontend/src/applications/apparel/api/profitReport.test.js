import { describe, expect, it } from "vitest";
import { marginLabel, profitQuery, profitRows, profitTotals, signedMinor, signedMoney } from "./profitReport";
import { periodRange } from "@/applications/apparel/lib/period";

// The server's profit report is the one place money can be negative: a loss-making variant has a
// negative gross_profit ("-50.00"), and revenue goes negative when returns exceed sales. money.js is
// documented NON-NEGATIVE on the wire, so this report parses the sign itself, rounds the magnitude
// through toMinor/fromMinor, and puts the sign back — never with float arithmetic, never NaN.

describe("signedMoney / signedMinor", () => {
  it("keeps a negative amount negative", () => {
    expect(signedMinor("-50.00")).toBe(-5000);
    expect(signedMoney("-50.00")).toBe(-50);
    expect(signedMoney("-0.5")).toBe(-0.5);
    expect(signedMinor("-0.01")).toBe(-1);
  });
  it("keeps a positive amount exactly as it was", () => {
    expect(signedMinor("12.34")).toBe(1234);
    expect(signedMoney("12.34")).toBe(12.34);
    expect(signedMoney("0")).toBe(0);
  });
  it("zero is zero, and '-0.00' is 0 and NOT -0", () => {
    expect(signedMinor("0.00")).toBe(0);
    expect(signedMinor("-0.00")).toBe(0);
    expect(Object.is(signedMinor("-0.00"), -0)).toBe(false);
    expect(Object.is(signedMoney("-0.00"), -0)).toBe(false);
    expect(Object.is(signedMoney("-0"), -0)).toBe(false);
    expect(signedMoney("-0.004")).toBe(0);
    expect(Object.is(signedMoney("-0.004"), -0)).toBe(false);
  });
  it("rounds the MAGNITUDE half-up, so a negative rounds away from zero exactly like a positive", () => {
    // 12.345 -> 12.35 and -12.345 -> -12.35; truncating the sign first must not change the rounding.
    expect(signedMinor("12.345")).toBe(1235);
    expect(signedMinor("-12.345")).toBe(-1235);
    expect(signedMinor("0.005")).toBe(1);
    expect(signedMinor("-0.005")).toBe(-1);
    expect(signedMinor("-2.675")).toBe(-268);
  });
  it("rounds on the DECIMAL TEXT, not on a float product (the money.js rule)", () => {
    // 1.005 * 100 is 100.49999999999999 and 0.145 * 100 is 14.499999999999998 in binary floating
    // point, so Math.round(x * 100) would give 100 and 14. The text path must still round HALF_UP.
    expect(signedMinor("1.005")).toBe(101);
    expect(signedMinor("-1.005")).toBe(-101);
    expect(signedMinor("0.145")).toBe(15);
    expect(signedMinor("-0.145")).toBe(-15);
    expect(signedMinor("8.165")).toBe(817);
    expect(signedMinor("-8.165")).toBe(-817);
    expect(signedMinor("2.675")).toBe(268);
  });
  it("a missing figure is zero, not NaN", () => {
    expect(signedMinor(null)).toBe(0);
    expect(signedMinor(undefined)).toBe(0);
    expect(signedMoney(null)).toBe(0);
    expect(signedMoney(undefined)).toBe(0);
    expect(Number.isNaN(signedMoney(null))).toBe(false);
  });
  it("accepts a number as well as a string, and keeps its sign", () => {
    expect(signedMinor(-50)).toBe(-5000);
    expect(signedMinor(-0.5)).toBe(-50);
    expect(signedMinor(1e3)).toBe(100_000);
    expect(signedMinor(-0)).toBe(0);
    expect(Object.is(signedMinor(-0), -0)).toBe(false);
  });
  it("takes a NUMBER straight to toMinor, so a small exponent form is not rejected as text", () => {
    // String(1e-7) is "1e-7", which is not decimal text; toMinor(number) expands it instead of throwing.
    expect(signedMinor(1e-7)).toBe(0);
    expect(signedMinor(-1e-7)).toBe(0);
    expect(Object.is(signedMinor(-1e-7), -0)).toBe(false);
    expect(signedMinor(1.5e2)).toBe(15_000);
    // The same amount written as text is not a decimal string, and must throw rather than guess.
    expect(() => signedMinor("1e-7")).toThrow();
  });
  it("tolerates surrounding whitespace and an explicit plus", () => {
    expect(signedMinor(" -50.00 ")).toBe(-5000);
    expect(signedMinor("+12.50")).toBe(1250);
  });
  it("throws on garbage instead of returning NaN", () => {
    expect(() => signedMinor("abc")).toThrow();
    expect(() => signedMinor("1e3")).toThrow();
    expect(() => signedMinor("1,50")).toThrow();
    expect(() => signedMinor("--5")).toThrow();
    expect(() => signedMinor(NaN)).toThrow();
    expect(() => signedMinor(Infinity)).toThrow();
  });
});

describe("profitRows", () => {
  const loss = {
    variant_id: "v-loss",
    model: "تيشيرت",
    season: "صيف",
    brand_id: "b1",
    size: "M",
    colour: "أسود",
    units_sold: 2,
    units_returned: 0,
    revenue: "100.00",
    cost: "150.00",
    gross_profit: "-50.00",
    margin_pct: "-50.00",
    units_without_cost: 0,
    cost_returned_is_estimate: false,
  };
  const winner = {
    variant_id: "v-win",
    model: "بنطلون",
    season: "شتاء",
    brand_id: null,
    size: "L",
    colour: "أزرق",
    units_sold: 1,
    units_returned: 0,
    revenue: "200.00",
    cost: "120.00",
    gross_profit: "80.00",
    margin_pct: "40.00",
    units_without_cost: 0,
    cost_returned_is_estimate: false,
  };

  it("reads a loss-making row with its profit negative, not as NaN or a dropped row", () => {
    const [row] = profitRows([loss]);
    expect(row.profit).toBe(-50);
    expect(row.margin).toBe(-50);
    expect(row.revenue).toBe(100);
    expect(row.cost).toBe(150);
    expect(Number.isNaN(row.profit)).toBe(false);
  });
  it("leaves a normal positive row unchanged", () => {
    const [row] = profitRows([winner]);
    expect(row).toMatchObject({ id: "v-win", revenue: 200, cost: 120, profit: 80, margin: 40, unitsSold: 1 });
  });
  it("keeps the server's order (worst first) and maps both rows independently", () => {
    const rows = profitRows([loss, winner]);
    expect(rows.map((r) => r.id)).toEqual(["v-loss", "v-win"]);
    expect(rows.map((r) => r.profit)).toEqual([-50, 80]);
  });
  it("revenue goes negative when returns exceed sales", () => {
    const [row] = profitRows([{ variant_id: "v-ret", revenue: "-25.50", cost: "0.00", gross_profit: "-25.50", margin_pct: null }]);
    // The SIGN is the point: a revenue of -25.50 must not read as 25.50 (which the non-negative
    // money path would throw on, and a magnitude-only path would silently report as a gain).
    expect(row.revenue).toBe(-25.5);
    expect(row.revenue).toBeLessThan(0);
    expect(row.profit).toBe(-25.5);
    expect(row.margin).toBeNull();
  });
  it("negative revenue and a positive profit in the same row do not cancel", () => {
    const [row] = profitRows([{ variant_id: "v-mix", revenue: "-10.00", cost: "-40.00", gross_profit: "30.00", margin_pct: null }]);
    expect(row.revenue).toBe(-10);
    expect(row.cost).toBe(-40);
    expect(row.profit).toBe(30);
  });
  it("a zero row is zero, and '-0.00' is never -0", () => {
    const [row] = profitRows([{ variant_id: "v0", revenue: "0.00", cost: "0.00", gross_profit: "-0.00", margin_pct: "-0.00" }]);
    expect(row.revenue).toBe(0);
    expect(row.profit).toBe(0);
    expect(Object.is(row.profit, -0)).toBe(false);
    expect(Object.is(row.margin, -0)).toBe(false);
  });
  it("missing money fields read as zero instead of NaN", () => {
    const [row] = profitRows([{ variant_id: "v-null", revenue: null, cost: undefined, gross_profit: null, margin_pct: undefined }]);
    expect(row.revenue).toBe(0);
    expect(row.cost).toBe(0);
    expect(row.profit).toBe(0);
    expect(row.margin).toBeNull();
    expect(row.unitsSold).toBe(0);
    expect(row.unitsWithoutCost).toBe(0);
    expect(row.costIsEstimate).toBe(false);
  });
  it("an empty or missing response is an empty report", () => {
    expect(profitRows()).toEqual([]);
    expect(profitRows([])).toEqual([]);
  });
  it("cost can be negative too, if a return gives back more than the period booked", () => {
    const [row] = profitRows([{ variant_id: "v-c", revenue: "10.00", cost: "-5.00", gross_profit: "15.00", margin_pct: "150.00" }]);
    expect(row.cost).toBe(-5);
    expect(row.profit).toBe(15);
  });
});

describe("profitTotals", () => {
  it("totals a losing period with a negative profit and margin", () => {
    const t = profitTotals({
      units_sold: 3,
      revenue: "300.00",
      cost: "380.00",
      gross_profit: "-80.00",
      margin_pct: "-26.67",
      units_without_cost: 1,
      cost_is_complete: false,
    });
    expect(t).toEqual({
      unitsSold: 3,
      revenue: 300,
      cost: 380,
      profit: -80,
      margin: -26.67,
      unitsWithoutCost: 1,
      costIsComplete: false,
      unitsReturned: 0,
      unitsReturnedToShelf: 0,
      returnedByCondition: {},
    });
  });
  it("negative revenue totals stay negative", () => {
    const t = profitTotals({ revenue: "-10.25", cost: "0.00", gross_profit: "-10.25", margin_pct: null });
    expect(t.revenue).toBe(-10.25);
    expect(t.revenue).toBeLessThan(0);
    expect(t.cost).toBe(0);
    expect(t.profit).toBe(-10.25);
    expect(t.margin).toBeNull();
  });
  it("'-0.00' totals are 0, not -0", () => {
    const t = profitTotals({ revenue: "-0.00", cost: "-0.00", gross_profit: "-0.00", margin_pct: "-0.00" });
    expect(Object.is(t.revenue, -0)).toBe(false);
    expect(Object.is(t.profit, -0)).toBe(false);
    expect(Object.is(t.margin, -0)).toBe(false);
    expect(t).toMatchObject({ revenue: 0, cost: 0, profit: 0, margin: 0 });
  });
  it("a missing totals object is a zero report, not a crash", () => {
    expect(profitTotals()).toEqual({
      unitsSold: 0,
      revenue: 0,
      cost: 0,
      profit: 0,
      margin: null,
      unitsWithoutCost: 0,
      costIsComplete: false,
      unitsReturned: 0,
      unitsReturnedToShelf: 0,
      returnedByCondition: {},
    });
    expect(profitTotals(null)).toMatchObject({ revenue: 0, profit: 0, margin: null });
    expect(profitTotals({})).toMatchObject({ revenue: 0, profit: 0, margin: null });
  });
  it("cost_is_complete is only true when the server says exactly true", () => {
    expect(profitTotals({ cost_is_complete: true }).costIsComplete).toBe(true);
    expect(profitTotals({ cost_is_complete: "true" }).costIsComplete).toBe(false);
    expect(profitTotals({}).costIsComplete).toBe(false);
  });
});

describe("marginLabel", () => {
  it("shows a negative margin with its sign", () => {
    expect(marginLabel(-26.67)).toBe("-26.7٪");
    expect(marginLabel(-0.04)).toBe("-0.0٪");
    expect(marginLabel(40)).toBe("40.0٪");
  });
  it("a null margin is a dash", () => {
    expect(marginLabel(null)).toBe("—");
    expect(marginLabel(undefined)).toBe("—");
  });
});

describe("profitQuery", () => {
  const now = new Date("2026-10-21T10:00:00Z");
  it("sends the day AFTER `until`, because the server's range ends before `end`", () => {
    expect(profitQuery({ period: "7d", now })).toBe("start=2026-10-15&end=2026-10-22");
    expect(profitQuery({ period: "today", now })).toBe("start=2026-10-21&end=2026-10-22");
  });
  it("adds the filters only when they are set", () => {
    expect(profitQuery({ period: "30d", brandId: "b1", season: " صيف ", now })).toBe(
      "start=2026-09-22&end=2026-10-22&brand_id=b1&season=%D8%B5%D9%8A%D9%81",
    );
    expect(profitQuery({ period: "7d", brandId: "", season: "   ", now })).toBe("start=2026-10-15&end=2026-10-22");
  });
});

// ---------------------------------------------------------------------------------------------
// The rest of the module, branch by branch. Everything below is deliberately explicit about the
// Cairo calendar day (not the UTC date), the half-open server range, and the difference between
// "no figure" (null) and "a figure that happens to be zero" (0) — a margin of 0 is a real margin.
// ---------------------------------------------------------------------------------------------

/** Independent re-implementation of "+1 day on a date key", so a bug in the module cannot hide. */
const nextDay = (key) => {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
};

describe("profitQuery: the Cairo period and the half-open server range", () => {
  it("period 'today' at 2026-11-21T10:00Z is start=2026-11-21 end=2026-11-22", () => {
    expect(profitQuery({ period: "today", now: new Date("2026-11-21T10:00:00Z") })).toBe(
      "start=2026-11-21&end=2026-11-22",
    );
  });

  it("uses the CAIRO date for 'today', not the UTC date (00:30 in Cairo is still yesterday in UTC)", () => {
    // 2026-11-20T22:30Z is 00:30 on 2026-11-21 in Cairo (UTC+2 in November), so "today" is the 21st.
    const q = profitQuery({ period: "today", now: new Date("2026-11-20T22:30:00Z") });
    expect(q).toBe("start=2026-11-21&end=2026-11-22");
    // Spelled out, so a UTC-date implementation fails loudly and for the right reason.
    const p = new URLSearchParams(q);
    expect(p.get("start")).toBe("2026-11-21");
    expect(p.get("start")).not.toBe("2026-11-20");
    expect(p.get("end")).not.toBe("2026-11-21");
  });

  it("'7d' starts 6 days before `until`, so the range is 7 days inclusive", () => {
    const p = new URLSearchParams(profitQuery({ period: "7d", now: new Date("2026-11-21T10:00:00Z") }));
    expect(p.get("start")).toBe("2026-11-15");
    expect(p.get("end")).toBe("2026-11-22");
    // start + 6 days == the last included day; end is the day after it.
    expect(nextDay(p.get("start"))).not.toBe(p.get("end"));
  });

  it("'30d' starts 29 days before `until`", () => {
    const p = new URLSearchParams(profitQuery({ period: "30d", now: new Date("2026-11-21T10:00:00Z") }));
    expect(p.get("start")).toBe("2026-10-23");
    expect(p.get("end")).toBe("2026-11-22");
  });

  it("an unknown period falls back to 7 days, exactly like periodRange does", () => {
    const now = new Date("2026-11-21T10:00:00Z");
    expect(profitQuery({ period: "90d", now })).toBe(profitQuery({ period: "7d", now }));
    expect(profitQuery({ period: "", now })).toBe("start=2026-11-15&end=2026-11-22");
  });

  it("rolls the end over a month boundary (2026-11-30 -> 2026-12-01)", () => {
    expect(profitQuery({ period: "today", now: new Date("2026-11-30T10:00:00Z") })).toBe(
      "start=2026-11-30&end=2026-12-01",
    );
  });

  it("rolls the end over a year boundary (2026-12-31 -> 2027-01-01)", () => {
    expect(profitQuery({ period: "today", now: new Date("2026-12-31T10:00:00Z") })).toBe(
      "start=2026-12-31&end=2027-01-01",
    );
  });

  it("rolls the end over a 7d range that crosses the year boundary too", () => {
    expect(profitQuery({ period: "7d", now: new Date("2026-12-31T10:00:00Z") })).toBe(
      "start=2026-12-25&end=2027-01-01",
    );
  });

  it("rolls Feb 28 of a non-leap year to Mar 1 (2027-02-28 -> 2027-03-01)", () => {
    expect(profitQuery({ period: "today", now: new Date("2027-02-28T10:00:00Z") })).toBe(
      "start=2027-02-28&end=2027-03-01",
    );
  });

  it("rolls a leap day to Mar 1 (2028-02-29 -> 2028-03-01), and the 7d start crosses the month", () => {
    expect(profitQuery({ period: "today", now: new Date("2028-02-29T10:00:00Z") })).toBe(
      "start=2028-02-29&end=2028-03-01",
    );
    expect(profitQuery({ period: "7d", now: new Date("2028-02-29T10:00:00Z") })).toBe(
      "start=2028-02-23&end=2028-03-01",
    );
  });

  it("sends brand_id only when it is set", () => {
    const now = new Date("2026-11-21T10:00:00Z");
    const withBrand = new URLSearchParams(profitQuery({ period: "7d", brandId: "b1", now }));
    expect(withBrand.get("brand_id")).toBe("b1");
    for (const brandId of ["", undefined, null]) {
      const p = new URLSearchParams(profitQuery({ period: "7d", brandId, now }));
      expect(p.has("brand_id")).toBe(false);
      expect(p.toString()).toBe("start=2026-11-15&end=2026-11-22");
    }
  });

  it("sends season only when it is non-blank, and trims it", () => {
    const now = new Date("2026-11-21T10:00:00Z");
    const p = new URLSearchParams(profitQuery({ period: "7d", season: "  صيف  ", now }));
    expect(p.get("season")).toBe("صيف");
    expect(p.get("season")).not.toBe("  صيف  ");
    for (const season of ["", "   ", "\t\n ", undefined, null]) {
      expect(new URLSearchParams(profitQuery({ period: "7d", season, now })).has("season")).toBe(false);
    }
  });

  it("uses exactly the parameter names start, end, brand_id, season", () => {
    const now = new Date("2026-11-21T10:00:00Z");
    expect([...new URLSearchParams(profitQuery({ period: "7d", now })).keys()]).toEqual(["start", "end"]);
    expect(
      [...new URLSearchParams(profitQuery({ period: "7d", brandId: "b1", season: "صيف", now })).keys()],
    ).toEqual(["start", "end", "brand_id", "season"]);
    // And the values are plain date keys, not ISO instants.
    const p = new URLSearchParams(profitQuery({ period: "7d", now }));
    for (const key of ["start", "end"]) expect(p.get(key)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("works with no argument at all, and with an empty object", () => {
    // Defaults: period 7d and `now` = the real clock. Both calls must agree with periodRange.
    const { since, until } = periodRange("7d");
    const expected = `start=${since}&end=${nextDay(until)}`;
    expect(profitQuery()).toBe(expected);
    expect(profitQuery({})).toBe(expected);
  });
});

describe("profitRows: field mapping and coercion", () => {
  it("null (or absent) season/brand_id/size/colour/model become '' — except brand_id, which is null", () => {
    const [row] = profitRows([
      { variant_id: "v-nulls", model: null, season: null, brand_id: null, size: null, colour: null },
    ]);
    expect(row).toMatchObject({ id: "v-nulls", model: "", season: "", size: "", colour: "" });
    expect(row.brandId).toBeNull();
  });

  it("a brand_id of '' stays '' rather than collapsing to null", () => {
    const [row] = profitRows([{ variant_id: "v-empty-brand", brand_id: "" }]);
    expect(row.brandId).toBe("");
    expect(row.brandId).not.toBeNull();
  });

  it("keeps a real season/model/size/colour string untouched", () => {
    const [row] = profitRows([{ variant_id: "v", model: "تيشيرت", season: "صيف", size: "M", colour: "أسود" }]);
    expect(row).toMatchObject({ model: "تيشيرت", season: "صيف", size: "M", colour: "أسود" });
  });

  it("coerces units_sold / units_returned / units_without_cost from strings to numbers", () => {
    const [row] = profitRows([
      { variant_id: "v", units_sold: "2", units_returned: "1", units_without_cost: "3" },
    ]);
    expect(row.unitsSold).toBe(2);
    expect(row.unitsReturned).toBe(1);
    expect(row.unitsWithoutCost).toBe(3);
    for (const key of ["unitsSold", "unitsReturned", "unitsWithoutCost"]) expect(typeof row[key]).toBe("number");
  });

  it("missing unit counts are 0, not NaN", () => {
    const [row] = profitRows([{ variant_id: "v" }]);
    expect(row.unitsSold).toBe(0);
    expect(row.unitsReturned).toBe(0);
    expect(row.unitsWithoutCost).toBe(0);
  });

  it("margin: null stays null, 0 stays 0, and a negative keeps its sign", () => {
    const [none] = profitRows([{ variant_id: "a", margin_pct: null }]);
    const [zero] = profitRows([{ variant_id: "b", margin_pct: 0 }]);
    const [zeroText] = profitRows([{ variant_id: "c", margin_pct: "0.00" }]);
    const [negZero] = profitRows([{ variant_id: "d", margin_pct: "-0.00" }]);
    const [negative] = profitRows([{ variant_id: "e", margin_pct: "-12.50" }]);
    expect(none.margin).toBeNull();
    // A margin of 0 is a real, meaningful margin ("sold at cost") — it must NOT become null.
    expect(zero.margin).toBe(0);
    expect(zero.margin).not.toBeNull();
    expect(zeroText.margin).toBe(0);
    expect(negZero.margin).toBe(0);
    expect(Object.is(negZero.margin, -0)).toBe(false);
    expect(negative.margin).toBe(-12.5);
    expect(negative.margin).toBeLessThan(0);
  });

  it("an absent margin_pct is null, not NaN", () => {
    const [row] = profitRows([{ variant_id: "v" }]);
    expect(row.margin).toBeNull();
    expect(Number.isNaN(row.margin)).toBe(false);
  });

  it("a loss-making row keeps BOTH signs: negative gross_profit and negative margin_pct", () => {
    const [row] = profitRows([
      { variant_id: "v-loss2", revenue: "80.00", cost: "100.00", gross_profit: "-20.00", margin_pct: "-25.00" },
    ]);
    expect(row.profit).toBe(-20);
    expect(row.margin).toBe(-25);
    expect(Math.sign(row.profit)).toBe(-1);
    expect(Math.sign(row.margin)).toBe(-1);
  });

  it("costIsEstimate is a boolean, true only for a truthy cost_returned_is_estimate", () => {
    const flag = (v) => profitRows([{ variant_id: "v", cost_returned_is_estimate: v }])[0].costIsEstimate;
    expect(flag(true)).toBe(true);
    expect(flag(1)).toBe(true);
    expect(flag("yes")).toBe(true);
    for (const v of [false, 0, "", null, undefined]) expect(flag(v)).toBe(false);
    // The type matters: a raw 1 or "yes" must be normalised, not passed through.
    expect(typeof flag(1)).toBe("boolean");
    expect(typeof flag("yes")).toBe("boolean");
  });

  it("the row id IS variant_id", () => {
    const [row] = profitRows([{ variant_id: "var-42", revenue: "1.00" }]);
    expect(row.id).toBe("var-42");
    expect(row.variant_id).toBeUndefined();
  });
});

describe("profitTotals: missing data, zero margins and the completeness flag", () => {
  it("undefined and null input give zeros, a null margin and costIsComplete false", () => {
    const zeros = {
      unitsSold: 0,
      revenue: 0,
      cost: 0,
      profit: 0,
      margin: null,
      unitsWithoutCost: 0,
      costIsComplete: false,
      unitsReturned: 0,
      unitsReturnedToShelf: 0,
      returnedByCondition: {},
    };
    expect(profitTotals()).toEqual(zeros);
    expect(profitTotals(null)).toEqual(zeros);
    expect(profitTotals(undefined)).toEqual(zeros);
  });

  it("costIsComplete is true ONLY for exactly boolean true", () => {
    expect(profitTotals({ cost_is_complete: true }).costIsComplete).toBe(true);
    for (const v of ["true", 1, "yes", "1", {}, [], false, 0, null, undefined]) {
      expect(profitTotals({ cost_is_complete: v }).costIsComplete).toBe(false);
    }
  });

  it("margin: null stays null, 0 stays 0 (not null), negative keeps its sign", () => {
    expect(profitTotals({ margin_pct: null }).margin).toBeNull();
    expect(profitTotals({}).margin).toBeNull();
    expect(profitTotals({ margin_pct: 0 }).margin).toBe(0);
    expect(profitTotals({ margin_pct: "0.00" }).margin).toBe(0);
    expect(profitTotals({ margin_pct: 0 }).margin).not.toBeNull();
    const neg = profitTotals({ margin_pct: "-12.50" }).margin;
    expect(neg).toBe(-12.5);
    expect(neg).toBeLessThan(0);
    expect(Object.is(profitTotals({ margin_pct: "-0.00" }).margin, -0)).toBe(false);
  });

  it("coerces the unit counts from strings", () => {
    const t = profitTotals({ units_sold: "5", units_without_cost: "2" });
    expect(t.unitsSold).toBe(5);
    expect(t.unitsWithoutCost).toBe(2);
    expect(typeof t.unitsSold).toBe("number");
    expect(typeof t.unitsWithoutCost).toBe("number");
  });

  it("a loss-making period keeps a negative profit and a negative margin", () => {
    const t = profitTotals({ gross_profit: "-80.00", margin_pct: "-26.67", revenue: "300.00", cost: "380.00" });
    expect(t.profit).toBe(-80);
    expect(t.margin).toBe(-26.67);
    expect(Math.sign(t.profit)).toBe(-1);
    expect(Math.sign(t.margin)).toBe(-1);
  });
});

describe("marginLabel: dash, zero, sign and one-decimal rounding", () => {
  it("null and undefined are the em dash", () => {
    expect(marginLabel(null)).toBe("—");
    expect(marginLabel(undefined)).toBe("—");
    expect(marginLabel(null)).not.toContain("٪");
  });

  it("zero is '0.0٪', NOT the dash — a 0% margin is a real figure", () => {
    expect(marginLabel(0)).toBe("0.0٪");
    expect(marginLabel(0)).not.toBe("—");
    expect(marginLabel(-0)).toBe("0.0٪");
    expect(marginLabel("0.00")).toBe("0.0٪");
    expect(marginLabel("-0.00")).toBe("0.0٪");
    expect(marginLabel(false)).toBe("0.0٪");
  });

  it("a negative margin keeps its sign", () => {
    expect(marginLabel(-12.5)).toBe("-12.5٪");
    expect(marginLabel(-26.67)).toBe("-26.7٪");
    expect(marginLabel("-12.50")).toBe("-12.5٪");
  });

  it("rounds to exactly one decimal", () => {
    expect(marginLabel(12.34)).toBe("12.3٪");
    expect(marginLabel(12.36)).toBe("12.4٪");
    expect(marginLabel(33.333)).toBe("33.3٪");
    expect(marginLabel(12.96)).toBe("13.0٪");
    expect(marginLabel(99.95)).toBe("100.0٪");
    expect(marginLabel(-12.55)).toBe("-12.6٪");
    // One digit after the point, always — not zero, not two.
    expect(marginLabel(7)).toBe("7.0٪");
    expect(marginLabel(7)).not.toBe("7٪");
  });

  it("accepts string numbers", () => {
    expect(marginLabel("40.00")).toBe("40.0٪");
    expect(marginLabel("12.34")).toBe("12.3٪");
    expect(marginLabel("-0.04")).toBe("-0.0٪");
  });

  it("uses the Arabic percent sign U+066A, not ASCII '%'", () => {
    expect(marginLabel(40)).toBe(`40.0${String.fromCharCode(0x066a)}`);
    expect(marginLabel(40)).not.toContain("%");
  });
});
