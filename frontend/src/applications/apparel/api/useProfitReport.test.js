import { beforeEach, describe, expect, it, vi } from "vitest";

const seen = [];
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options) => {
    seen.push(options);
    return { options };
  },
}));
const profitByVariant = vi.fn(async () => ({ rows: [], totals: {} }));
vi.mock("./posApi", () => ({ posApi: { profitByVariant: (...a) => profitByVariant(...a) } }));

import { PROFIT_KEY, shapeProfit, shouldRetryProfit, useProfitReport } from "./useProfitReport";
import { profitQuery } from "./profitReport";

beforeEach(() => {
  seen.length = 0;
  profitByVariant.mockClear();
});

describe("which failures are retried", () => {
  it("never a refusal: 403 and 401 give the same answer again", () => {
    expect(shouldRetryProfit(0, { status: 403 })).toBe(false);
    expect(shouldRetryProfit(0, { status: 401 })).toBe(false);
  });
  it("anything else once, then stops", () => {
    expect(shouldRetryProfit(0, { status: 500 })).toBe(true);
    expect(shouldRetryProfit(0, { status: 0 })).toBe(true);
    expect(shouldRetryProfit(0, new Error("x"))).toBe(true);
    expect(shouldRetryProfit(1, { status: 500 })).toBe(false);
    expect(shouldRetryProfit(2, { status: 500 })).toBe(false);
  });
});

describe("the query the hook runs", () => {
  const now = new Date();
  it("the key carries the exact window, so two windows never share an answer", () => {
    useProfitReport({ period: "7d" });
    useProfitReport({ period: "30d" });
    expect(seen[0].queryKey.slice(0, PROFIT_KEY.length)).toEqual(PROFIT_KEY);
    expect(seen[0].queryKey).not.toEqual(seen[1].queryKey);
  });
  it("brand and season are part of the key too", () => {
    useProfitReport({ period: "7d" });
    useProfitReport({ period: "7d", brandId: "b1" });
    useProfitReport({ period: "7d", season: "SS26" });
    const keys = seen.map((s) => JSON.stringify(s.queryKey));
    expect(new Set(keys).size).toBe(3);
  });
  it("the server is asked with the same query string the key names, brand and season included", async () => {
    useProfitReport({ period: "today", brandId: "b1", season: " SS26 " });
    await seen[0].queryFn();
    const expected = profitQuery({ period: "today", brandId: "b1", season: " SS26 ", now });
    expect(profitByVariant).toHaveBeenCalledTimes(1);
    const sent = new URLSearchParams(profitByVariant.mock.calls[0][0]);
    expect(sent.get("brand_id")).toBe("b1");
    expect(sent.get("season")).toBe("SS26");
    expect(sent.get("start")).toBe(new URLSearchParams(expected).get("start"));
    expect(sent.get("end")).toBe(new URLSearchParams(expected).get("end"));
  });
  it("an empty brand and season send nothing", async () => {
    useProfitReport({ period: "7d" });
    await seen[0].queryFn();
    const sent = new URLSearchParams(profitByVariant.mock.calls[0][0]);
    expect(sent.has("brand_id")).toBe(false);
    expect(sent.has("season")).toBe(false);
  });
  it("a profit is never served from an old answer", () => {
    useProfitReport({});
    expect(seen[0].staleTime).toBe(0);
  });
  it("it waits for its tab: disabled when asked to, on by default", () => {
    useProfitReport({ enabled: false });
    useProfitReport({});
    expect(seen[0].enabled).toBe(false);
    expect(seen[1].enabled).toBe(true);
  });
  it("a refusal is not retried by the options it hands the query", () => {
    useProfitReport({});
    expect(seen[0].retry(0, { status: 403 })).toBe(false);
    expect(seen[0].retry(0, { status: 500 })).toBe(true);
  });
});

describe("the answer shaped for the table", () => {
  it("rows and totals come out shaped, and a missing answer is empty rather than a crash", () => {
    const shaped = shapeProfit({ rows: [{ variant_id: "v1", gross_profit: "-5.00", units_sold: 2 }], totals: { cost_is_complete: true } });
    expect(shaped.rows[0].id).toBe("v1");
    expect(shaped.rows[0].profit).toBe(-5);
    expect(shaped.totals.costIsComplete).toBe(true);
    expect(shapeProfit(undefined).rows).toEqual([]);
    expect(shapeProfit(null).totals.costIsComplete).toBe(false);
  });
});
