import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/query-core";

const getMock = vi.fn();
vi.mock("./importCenter", async () => {
  const actual = await vi.importActual("./importCenter");
  return { ...actual, getImportSession: (...a) => getMock(...a) };
});

import { IMPORT_KEY, POLL_MS, applySession, pollInterval, readSession } from "./useImportCenter";
import { STOCK_KEY } from "./useStock";

const KEY = (id) => [...IMPORT_KEY, "session", id];
let qc;
let invalidated;

beforeEach(() => {
  getMock.mockReset();
  qc = new QueryClient();
  invalidated = [];
  vi.spyOn(qc, "invalidateQueries").mockImplementation(({ queryKey }) => {
    invalidated.push(queryKey.join("/"));
  });
});

describe("pollInterval", () => {
  it("polls only while the import is running", () => {
    expect(pollInterval({ status: "running" })).toBe(POLL_MS);
    for (const status of ["analyzed", "mapped", "validated", "completed", "cancelled", "failed"])
      expect(pollInterval({ status }), status).toBe(false);
    expect(pollInterval(undefined)).toBe(false);
  });
});

describe("readSession", () => {
  it("re-reads stock and the recent list the moment a running import is seen finished", async () => {
    qc.setQueryData(KEY("s1"), { id: "s1", status: "running" });
    getMock.mockResolvedValue({ id: "s1", status: "completed" });
    const next = await readSession(qc, "s1");
    expect(next.status).toBe("completed");
    expect(invalidated).toContain(STOCK_KEY.join("/"));
    expect(invalidated).toContain([...IMPORT_KEY, "recent"].join("/"));
  });
  it("does not touch stock while the import is still running", async () => {
    qc.setQueryData(KEY("s1"), { id: "s1", status: "running" });
    getMock.mockResolvedValue({ id: "s1", status: "running" });
    await readSession(qc, "s1");
    expect(invalidated).toEqual([]);
  });
  it("does not touch stock for a session that was never running (first load, or a page reopened)", async () => {
    getMock.mockResolvedValue({ id: "s1", status: "completed" });
    await readSession(qc, "s1");
    expect(invalidated).toEqual([]);
  });
  it("also refreshes stock when a running import ends cancelled or failed (rows may have been applied)", async () => {
    for (const status of ["cancelled", "failed"]) {
      invalidated = [];
      qc.setQueryData(KEY("s1"), { id: "s1", status: "running" });
      getMock.mockResolvedValue({ id: "s1", status });
      await readSession(qc, "s1");
      expect(invalidated, status).toContain(STOCK_KEY.join("/"));
    }
  });
  it("hands the abort signal to the request", async () => {
    getMock.mockResolvedValue({ id: "s1", status: "analyzed" });
    const ctl = new AbortController();
    await readSession(qc, "s1", ctl.signal);
    expect(getMock).toHaveBeenCalledWith("s1", { signal: ctl.signal });
  });
});

describe("applySession", () => {
  it("keeps the sheets a step's short answer does not repeat", () => {
    qc.setQueryData(KEY("s1"), { id: "s1", status: "analyzed", sheets: { Products: { rows: 3 } } });
    applySession(qc, { id: "s1", status: "validated", stats: { rows: { Products: 3 } } });
    expect(qc.getQueryData(KEY("s1"))).toEqual({
      id: "s1",
      status: "validated",
      sheets: { Products: { rows: 3 } },
      stats: { rows: { Products: 3 } },
    });
  });
  it("creates the entry for a new upload", () => {
    applySession(qc, { id: "s2", status: "analyzed" });
    expect(qc.getQueryData(KEY("s2"))).toEqual({ id: "s2", status: "analyzed" });
  });
  it("asks for stock only when told to (cancelling a run that already applied rows)", () => {
    applySession(qc, { id: "s1", status: "validated" });
    expect(invalidated).not.toContain(STOCK_KEY.join("/"));
    invalidated = [];
    applySession(qc, { id: "s1", status: "cancelled" }, { refreshStock: true });
    expect(invalidated).toContain(STOCK_KEY.join("/"));
  });
  it("ignores an answer without an id", () => {
    applySession(qc, null);
    applySession(qc, {});
    expect(invalidated).toEqual([]);
  });
});
