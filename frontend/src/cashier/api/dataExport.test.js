import { describe, expect, it } from "vitest";
import { collectExport, totalRows } from "./dataExport";

const T = (key, load) => ({ key, label: key, load });
const NOW = () => new Date("2026-10-21T10:00:00Z");

describe("collectExport", () => {
  it("collects every table and counts the rows", async () => {
    const r = await collectExport({ now: NOW, tables: [T("a", async () => [1, 2, 3]), T("b", async () => ({ items: [1] })), T("c", async () => [])] });
    expect(r.payload.tables).toEqual({ a: [1, 2, 3], b: [1], c: [] });
    expect(r.counts.map((c) => c.count)).toEqual([3, 1, 0]);
    expect(totalRows(r.counts)).toBe(4);
    expect(r.failed).toEqual([]);
    expect(r.payload.exported_at).toBe("2026-10-21T10:00:00.000Z");
  });

  it("reports a failed table instead of pretending the file is complete", async () => {
    const r = await collectExport({ now: NOW, tables: [T("ok", async () => [1]), T("bad", async () => { throw new Error("500"); })] });
    expect(r.payload.tables).toEqual({ ok: [1] });
    expect(r.payload.failed_tables).toEqual(["bad"]);
    expect(r.failed.map((f) => f.key)).toEqual(["bad"]);
    expect(r.counts).toHaveLength(1);
  });

  it("treats an unexpected response shape as no rows rather than crashing", async () => {
    const r = await collectExport({ now: NOW, tables: [T("a", async () => null), T("b", async () => "x")] });
    expect(r.payload.tables).toEqual({ a: [], b: [] });
  });
});
