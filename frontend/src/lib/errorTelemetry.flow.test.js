import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// End to end through the REAL guardian: a failure is reported -> the telemetry subscriber -> fetch.
let fetchMock;
beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-07T12:00:00Z"));
  const store = () => { const d = {}; return { getItem: (k) => d[k] ?? null, setItem: (k, v) => { d[k] = v; } }; };
  fetchMock = vi.fn(async () => ({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("localStorage", store());
  vi.stubGlobal("sessionStorage", store());
  vi.stubGlobal("document", { cookie: "" });
  vi.stubGlobal("window", { location: { origin: "https://app.example", pathname: "/orders/new", search: "?token=SECRET" } });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

async function boot() {
  const { guardianReport } = await import("./guardian.js");
  const t = await import("./errorTelemetry.js");
  t._resetErrorTelemetryForTests();
  t.startErrorTelemetry();
  return { guardianReport };
}
const sent = () => fetchMock.mock.calls.map(([url, init]) => ({ url, body: JSON.parse(init.body) }));

describe("guardian -> telemetry", () => {
  it("sends a server failure to /public/telemetry as an error event with its status code", async () => {
    const { guardianReport } = await boot();
    guardianReport({ kind: "api", source: "/orders", message: "Internal error", status: 500 });
    const [call] = sent();
    expect(call.url).toMatch(/\/public\/telemetry$/);
    expect(call.body).toMatchObject({ event_type: "error", status_code: 500, path: "/orders/new" });
    expect(call.body.visitor_id).toBeTruthy();
  });

  it("never leaks the query string: the page had ?token=SECRET", async () => {
    const { guardianReport } = await boot();
    guardianReport({ kind: "window", source: "app.js", message: "boom" });
    expect(JSON.stringify(sent())).not.toContain("SECRET");
  });

  it("sends a plain JavaScript error with no status code", async () => {
    const { guardianReport } = await boot();
    guardianReport({ kind: "window", source: "app.js", message: "x is not a function" });
    expect("status_code" in sent()[0].body).toBe(false);
  });

  it("does not send the same failure twice (the guardian merges repeats)", async () => {
    const { guardianReport } = await boot();
    guardianReport({ kind: "api", source: "/a", message: "HTTP 500", status: 500 });
    vi.advanceTimersByTime(2000);
    guardianReport({ kind: "api", source: "/a", message: "HTTP 500", status: 500 });
    expect(sent()).toHaveLength(1);
  });

  it("throttles a burst of DIFFERENT failures to one per second", async () => {
    const { guardianReport } = await boot();
    for (let i = 0; i < 10; i++) guardianReport({ kind: "api", source: `/p${i}`, message: `HTTP 50${i}`, status: 500 });
    expect(sent()).toHaveLength(1);
    vi.advanceTimersByTime(1000);
    guardianReport({ kind: "api", source: "/later", message: "HTTP 502", status: 502 });
    expect(sent()).toHaveLength(2);
  });

  it("caps a session at 20 events", async () => {
    const { guardianReport } = await boot();
    for (let i = 0; i < 40; i++) {
      guardianReport({ kind: "api", source: `/q${i}`, message: `unique ${i}`, status: 500 });
      vi.advanceTimersByTime(1100);
    }
    expect(sent()).toHaveLength(20);
  });

  it("a failing telemetry call does not throw or recurse", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    const { guardianReport } = await boot();
    expect(() => guardianReport({ kind: "api", source: "/a", message: "HTTP 500", status: 500 })).not.toThrow();
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchMock).toHaveBeenCalledTimes(1); // it did not report its own failure
  });

  it("starting twice does not double-send", async () => {
    const { guardianReport } = await boot();
    (await import("./errorTelemetry.js")).startErrorTelemetry();
    guardianReport({ kind: "api", source: "/a", message: "HTTP 500", status: 500 });
    expect(sent()).toHaveLength(1);
  });
});
