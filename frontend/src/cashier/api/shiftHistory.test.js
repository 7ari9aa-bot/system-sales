import { describe, expect, it, vi } from "vitest";
import { loadAllSessions, REPORT_DAYS } from "./shiftHistory";

const day = (n) => ({ id: `d${n}`, opened_at: `2026-01-${String(n).padStart(2, "0")}T09:00:00Z` });
const page = (from, count) => Array.from({ length: count }, (_, i) => day(from + i));

describe("loadAllSessions", () => {
  it("walks every page until a short one, so the history is not cut at the first 50", async () => {
    const all = page(1, 120);
    const list = vi.fn(async (q) => {
      const offset = Number(/offset=(\d+)/.exec(q)?.[1] ?? 0);
      return all.slice(offset, offset + 50);
    });
    const out = await loadAllSessions(list);
    expect(out).toHaveLength(120);
    expect(new Set(out.map((s) => s.id)).size).toBe(120); // no day twice
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("stops after one call when everything fits in the first page", async () => {
    const list = vi.fn(async () => page(1, 7));
    expect(await loadAllSessions(list)).toHaveLength(7);
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("an empty history is an empty list", async () => {
    expect(await loadAllSessions(async () => [])).toEqual([]);
  });

  it("has a safety cap so a misbehaving server cannot loop forever", async () => {
    const list = vi.fn(async () => page(1, 50)); // always a full page
    const out = await loadAllSessions(list, { maxPages: 4 });
    expect(list).toHaveBeenCalledTimes(4);
    expect(out.length).toBeLessThanOrEqual(200);
  });

  it("a failure on a later page surfaces instead of returning a silently short history", async () => {
    let n = 0;
    const list = async () => {
      if (n++ === 1) throw new Error("boom");
      return page(1, 50);
    };
    await expect(loadAllSessions(list)).rejects.toThrow("boom");
  });
});

describe("REPORT_DAYS", () => {
  it("is a bounded number, so opening the log is not one request per day of history", () => {
    expect(REPORT_DAYS).toBeGreaterThan(0);
    expect(REPORT_DAYS).toBeLessThanOrEqual(60);
  });
});
