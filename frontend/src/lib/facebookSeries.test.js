import { describe, expect, it } from "vitest";
import { chartPath, dailySeries } from "@/lib/facebookApi";

const metric = (values) => ({ name: "page_media_view", values });

/** A Page insights metric comes as one value per day; the chart needs a clean, ordered series. */
describe("dailySeries", () => {
  it("keeps the days in date order with their numbers", () => {
    const s = dailySeries(metric([
      { value: 5, end_time: "2026-11-03T08:00:00+0000" },
      { value: 2, end_time: "2026-11-01T08:00:00+0000" },
      { value: 9, end_time: "2026-11-02T08:00:00+0000" },
    ]));
    expect(s.map((p) => p.value)).toEqual([2, 9, 5]);
    expect(s[0].day).toBe("2026-11-01");
  });
  it("drops a day Meta sent without a number, but keeps a real zero", () => {
    const s = dailySeries(metric([{ value: 0, end_time: "2026-11-01T08:00:00+0000" }, { value: null, end_time: "2026-11-02T08:00:00+0000" }, { end_time: "2026-11-03T08:00:00+0000" }]));
    expect(s).toEqual([{ day: "2026-11-01", value: 0 }]);
  });
  it("is empty for a metric with no values", () => {
    expect(dailySeries(metric([]))).toEqual([]);
    expect(dailySeries(undefined)).toEqual([]);
  });
});

describe("chartPath", () => {
  it("draws a line from the first day to the last inside the box, the highest value at the top", () => {
    const p = chartPath([{ value: 0 }, { value: 10 }, { value: 5 }], 200, 100);
    expect(p.line.startsWith("M0,100")).toBe(true);
    expect(p.line).toContain("L100,0");
    expect(p.line.endsWith("L200,50")).toBe(true);
  });
  it("closes the area under the line down to the floor", () => {
    const p = chartPath([{ value: 1 }, { value: 2 }], 100, 50);
    expect(p.area.endsWith("L100,50L0,50Z")).toBe(true);
  });
  it("draws a flat line mid-height when every day is the same, instead of dividing by zero", () => {
    const p = chartPath([{ value: 4 }, { value: 4 }, { value: 4 }], 100, 40);
    expect(p.line).not.toContain("NaN");
    expect(p.line).toBe("M0,20L50,20L100,20");
  });
  it("copes with one day or none", () => {
    expect(chartPath([{ value: 3 }], 100, 40).line).not.toContain("NaN");
    expect(chartPath([], 100, 40)).toEqual({ line: "", area: "" });
  });
});
