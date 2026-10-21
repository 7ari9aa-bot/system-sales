import { describe, expect, it } from "vitest";
import { salesRows, summarizeSales } from "./salesReport";
import { periodRange } from "../lib/period";

describe("salesRows", () => {
  const api = [
    { date: "2026-10-20", invoices: 2, pieces: 5, gross: "300.00", discount: "10.10", returns: "50.00", returns_count: 1, net: "239.90" },
    { date: "2026-10-21", invoices: 1, pieces: 2, gross: "100.00", discount: "0.00", returns: "0.00", returns_count: 0, net: "100.00" },
  ];
  it("turns money strings into numbers and sorts newest day first", () => {
    const r = salesRows(api);
    expect(r.map((x) => x.date)).toEqual(["2026-10-21", "2026-10-20"]);
    expect(r[1]).toMatchObject({ invoices: 2, pieces: 5, gross: 300, discount: 10.1, returns: 50, net: 239.9 });
  });
  it("an empty or missing response is an empty report, not an error", () => {
    expect(salesRows()).toEqual([]);
    expect(salesRows([])).toEqual([]);
  });
  it("totals exactly, with no float drift on cents", () => {
    const t = summarizeSales(salesRows([{ date: "a", invoices: 1, pieces: 1, gross: "0.10", discount: "0.00", returns: "0.00", net: "0.10" }, { date: "b", invoices: 1, pieces: 1, gross: "0.20", discount: "0.00", returns: "0.00", net: "0.20" }]));
    expect(t).toMatchObject({ invoices: 2, pieces: 2, gross: 0.3, net: 0.3 });
  });
});

describe("periodRange", () => {
  it("today is a one-day range", () => expect(periodRange("today", new Date("2026-10-21T10:00:00Z"))).toEqual({ since: "2026-10-21", until: "2026-10-21" }));
  it("7d reaches six days back, today included", () => expect(periodRange("7d", new Date("2026-10-21T10:00:00Z"))).toEqual({ since: "2026-10-15", until: "2026-10-21" }));
  it("30d crosses a month boundary correctly", () => expect(periodRange("30d", new Date("2026-10-21T10:00:00Z")).since).toBe("2026-09-22"));
  it("uses the SHOP day: 23:30 UTC is already the next day in Cairo", () => expect(periodRange("today", new Date("2026-10-20T23:30:00Z")).until).toBe("2026-10-21"));
  it("an unknown period falls back to 7 days", () => expect(periodRange("zzz", new Date("2026-10-21T10:00:00Z")).since).toBe("2026-10-15"));
});
