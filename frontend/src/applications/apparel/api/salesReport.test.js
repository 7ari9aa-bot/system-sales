import { describe, expect, it } from "vitest";
import { salesRows, summarizeSales, summarizeTopProducts, topProductRows } from "./salesReport";
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

describe("topProductRows", () => {
  const api = [
    { variant_id: "v1", product_title: "تيشيرت", sku: "T-1", sold_qty: 5, returned_qty: 2, net_qty: 3, net_revenue: "150.10" },
    { variant_id: "v2", product_title: null, sku: null, sold_qty: 1, returned_qty: 0, net_qty: 1, net_revenue: "0.20" },
  ];
  it("keeps the server's ranking and reads sold, returned and net quantities", () => {
    const r = topProductRows(api);
    expect(r.map((x) => x.id)).toEqual(["v1", "v2"]);
    expect(r.map((x) => x.rank)).toEqual([1, 2]);
    expect(r[0]).toMatchObject({ name: "تيشيرت", sku: "T-1", sold: 5, returned: 2, qty: 3, revenue: 150.1 });
  });
  it("a deleted product still shows a row instead of breaking", () => {
    expect(topProductRows(api)[1]).toMatchObject({ name: "صنف محذوف", sku: "" });
  });
  it("totals add exactly", () => {
    expect(summarizeTopProducts(topProductRows(api))).toEqual({ sold: 6, returned: 2, qty: 4, revenue: 150.3 });
  });
  it("empty is empty", () => expect(topProductRows()).toEqual([]));
});
