import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VISITOR_KEY, currentVisitorId, getOrCreate } from "./visitorId.js";

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = v; }, data };
}

afterEach(() => vi.unstubAllGlobals());

describe("currentVisitorId", () => {
  it("returns the id the tracker stored", () => {
    vi.stubGlobal("localStorage", fakeStorage({ [VISITOR_KEY]: "abc-12345678" }));
    expect(currentVisitorId()).toBe("abc-12345678");
  });
  it("returns null for a browser that was never tracked, and does NOT invent one", () => {
    const store = fakeStorage();
    vi.stubGlobal("localStorage", store);
    expect(currentVisitorId()).toBeNull();
    expect(Object.keys(store.data)).toEqual([]); // attributing a merchant to a made-up id would be a lie
  });
  it("returns null when storage throws (private mode, blocked cookies)", () => {
    vi.stubGlobal("localStorage", { getItem() { throw new Error("blocked"); } });
    expect(currentVisitorId()).toBeNull();
  });
});

describe("getOrCreate", () => {
  it("creates once and then returns the same value", () => {
    const store = fakeStorage();
    const first = getOrCreate(store, "k");
    expect(first).toBeTruthy();
    expect(getOrCreate(store, "k")).toBe(first);
  });
});
