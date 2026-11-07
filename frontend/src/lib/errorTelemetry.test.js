import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MAX_PER_SESSION,
  MIN_GAP_MS,
  shouldForward,
  statusFromMessage,
  toTelemetryEvent,
} from "./errorTelemetry.js";

const fresh = () => ({ sent: 0, lastAt: 0, seen: new Set() });
const ev = (over = {}) => ({ id: "e1", kind: "api", source: "/orders", message: "HTTP 503", count: 1, ...over });

describe("statusFromMessage", () => {
  it("reads an HTTP status out of a guardian message", () => {
    expect(statusFromMessage("HTTP 503")).toBe(503);
    expect(statusFromMessage("failed: HTTP 404 not found")).toBe(404);
  });
  it("returns null when there is none, or it is not a real status", () => {
    expect(statusFromMessage("TypeError: x is undefined")).toBeNull();
    expect(statusFromMessage("HTTP 999")).toBeNull();
    expect(statusFromMessage(undefined)).toBeNull();
  });
});

describe("shouldForward", () => {
  it("forwards a new failure", () => {
    expect(shouldForward(ev(), fresh(), 10_000)).toBe(true);
  });
  it("does not forward the same event twice", () => {
    const state = fresh();
    state.seen.add("e1");
    expect(shouldForward(ev(), state, 10_000)).toBe(false);
  });
  it("does not forward a repeat the guardian merged into an older entry", () => {
    expect(shouldForward(ev({ count: 3 }), fresh(), 10_000)).toBe(false);
  });
  it("throttles a burst: nothing within MIN_GAP_MS of the last send", () => {
    const state = { ...fresh(), lastAt: 10_000 };
    expect(shouldForward(ev(), state, 10_000 + MIN_GAP_MS - 1)).toBe(false);
    expect(shouldForward(ev(), state, 10_000 + MIN_GAP_MS)).toBe(true);
  });
  it("stops at the per-session cap so a render loop cannot flood the API", () => {
    expect(shouldForward(ev(), { ...fresh(), sent: MAX_PER_SESSION }, 1e9)).toBe(false);
    expect(shouldForward(ev(), { ...fresh(), sent: MAX_PER_SESSION - 1 }, 1e9)).toBe(true);
  });
  it("ignores an empty event", () => {
    expect(shouldForward(null, fresh(), 10_000)).toBe(false);
  });
});

describe("toTelemetryEvent", () => {
  const ctx = { visitorId: "v-12345678", sessionId: "s-12345678", path: "/orders", origin: "https://app.example" };

  it("carries the explicit status code, which is what the owner's Errors page filters on", () => {
    const out = toTelemetryEvent(ev({ status: 502, message: "Bad gateway" }), ctx);
    expect(out.event_type).toBe("error");
    expect(out.status_code).toBe(502);
  });
  it("falls back to the status in the message when none was passed", () => {
    expect(toTelemetryEvent(ev({ message: "HTTP 500" }), ctx).status_code).toBe(500);
  });
  it("omits status_code for a plain JavaScript error", () => {
    const out = toTelemetryEvent(ev({ kind: "window", message: "x is not a function", status: null }), ctx);
    expect("status_code" in out).toBe(false);
  });
  it("uses the route only and never a query string", () => {
    const out = toTelemetryEvent(ev(), ctx);
    expect(out.path).toBe("/orders");
    expect(out.url).toBe("https://app.example/orders");
  });
  it("cuts a very long message", () => {
    expect(toTelemetryEvent(ev({ message: "x".repeat(5000) }), ctx).element.length).toBeLessThanOrEqual(300);
  });
  it("keeps the kind and source so the owner can tell a render crash from a failed request", () => {
    expect(toTelemetryEvent(ev({ kind: "render", source: "Boundary" }), ctx).metadata).toEqual({
      kind: "render",
      source: "Boundary",
    });
  });
});

describe("api.shouldReportFailure: which failures reach the owner", () => {
  let shouldReportFailure;
  beforeEach(async () => {
    vi.stubGlobal("document", { cookie: "" });
    vi.stubGlobal("window", { location: { origin: "http://localhost" } });
    ({ shouldReportFailure } = await import("./api.js"));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("reports a server error on a WRITE (a failed save or payment is as serious as a failed read)", () => {
    expect(shouldReportFailure("POST", "/orders", { status: 500 })).toBe(true);
    expect(shouldReportFailure("PUT", "/products/1", { status: 503 })).toBe(true);
    expect(shouldReportFailure("DELETE", "/products/1", { status: 502 })).toBe(true);
  });
  it("reports a network failure or timeout on a write", () => {
    expect(shouldReportFailure("POST", "/orders", { status: 0 })).toBe(true);
  });
  it("does NOT report a client error on a write: that is the user's own input being refused", () => {
    expect(shouldReportFailure("POST", "/customers", { status: 422 })).toBe(false);
    expect(shouldReportFailure("POST", "/customers", { status: 409 })).toBe(false);
    expect(shouldReportFailure("PUT", "/products/1", { status: 403 })).toBe(false);
  });
  it("still reports any failed read, as before", () => {
    expect(shouldReportFailure("GET", "/orders", { status: 404 })).toBe(true);
    expect(shouldReportFailure("GET", "/orders", { status: 500 })).toBe(true);
  });
  it("never reports auth endpoints: a wrong password is an expected outcome, not a fault", () => {
    expect(shouldReportFailure("POST", "/auth/login", { status: 500 })).toBe(false);
    expect(shouldReportFailure("POST", "/auth/register", { status: 500 })).toBe(false);
    expect(shouldReportFailure("GET", "/auth/me", { status: 401 })).toBe(false);
  });
});
