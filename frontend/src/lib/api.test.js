import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// api.js reads document.cookie for the CSRF header and the session marker.
let cookie = "";
beforeEach(() => {
  cookie = "csrf_token=abc123";
  vi.stubGlobal("document", {
    get cookie() { return cookie; },
    set cookie(v) { cookie = v; },
  });
  vi.stubGlobal("window", { location: { origin: "http://localhost" } });
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.resetModules();
});

const json = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

async function load() {
  return import("./api.js");
}

/** A fetch that never answers until its signal aborts, like a hung server. */
function hangingFetch() {
  return vi.fn((_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => {
      reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
    });
  }));
}

describe("api() timeouts", () => {
  it("rejects a hung request with a retryable timeout ApiError", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { api, ApiError, REQUEST_TIMEOUT_MS } = await load();
    const pending = api("/inbox").catch((e) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    const err = await pending;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("timeout");
    expect(err.retryable).toBe(true);
    expect(err.status).toBe(0);
  });

  it("does not time out a request that answers in time", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, { ok: 1 })));
    const { api } = await load();
    await expect(api("/inbox")).resolves.toEqual({ ok: 1 });
  });

  it("gives raw-body uploads the longer budget", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { api, REQUEST_TIMEOUT_MS, UPLOAD_TIMEOUT_MS } = await load();
    let settled = false;
    const pending = api("/products/1/images/upload", {
      method: "POST", body: new Uint8Array([1]), rawBody: true,
    }).catch((e) => { settled = true; return e; });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    expect(settled).toBe(false); // still waiting after the normal limit
    await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS - REQUEST_TIMEOUT_MS + 1);
    expect((await pending).code).toBe("timeout");
  });

  it("honours a per-call timeoutMs override", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { api } = await load();
    const pending = api("/x", { timeoutMs: 500 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(501);
    expect((await pending).code).toBe("timeout");
  });
});

describe("api() caller abort", () => {
  it("re-throws AbortError untouched (not a network or timeout error)", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { api } = await load();
    const ctrl = new AbortController();
    const pending = api("/search?q=a", { signal: ctrl.signal }).catch((e) => e);
    ctrl.abort();
    const err = await pending;
    expect(err.name).toBe("AbortError");
    expect(err.code).toBeUndefined();
  });

  it("rejects immediately when the signal is already aborted", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { api } = await load();
    const ctrl = new AbortController();
    ctrl.abort();
    const fetchMock = globalThis.fetch;
    const err = await api("/x", { signal: ctrl.signal }).catch((e) => e);
    expect(err.name).toBe("AbortError");
    expect(fetchMock).not.toHaveBeenCalled(); // never even sent
  });
});

describe("api() existing behaviour is preserved", () => {
  it("sends the CSRF header on mutations only", async () => {
    const fetchMock = vi.fn(async () => json(200, {}));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await load();
    await api("/a");
    await api("/a", { method: "POST", body: { x: 1 } });
    expect(fetchMock.mock.calls[0][1].headers["X-CSRF-Token"]).toBeUndefined();
    expect(fetchMock.mock.calls[1][1].headers["X-CSRF-Token"]).toBe("abc123");
    expect(fetchMock.mock.calls[1][1].credentials).toBe("include");
  });

  it("refreshes once on 401 and retries the original request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "expired" } }))
      .mockResolvedValueOnce(json(200, { access_token: "t" })) // /auth/refresh
      .mockResolvedValueOnce(json(200, { data: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await load();
    await expect(api("/inbox")).resolves.toEqual({ data: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toContain("/auth/refresh");
  });

  it("does NOT refresh on a real 403 permission denial", async () => {
    const fetchMock = vi.fn(async () =>
      json(403, { error: { code: "permission_denied", message: "settings:write required" } }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await load();
    const err = await api("/invitations").catch((e) => e);
    expect(err.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes on the legacy 403 'invalid token' serialization", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(403, { error: { code: "permission_denied", message: "Invalid token" } }))
      .mockResolvedValueOnce(json(200, { access_token: "t" }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await load();
    await expect(api("/inbox")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not loop: a second 401 after refresh is terminal", async () => {
    const unauth = () => json(401, { error: { code: "unauthorized", message: "no" } });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(unauth())
      .mockResolvedValueOnce(json(200, { access_token: "t" }))
      .mockResolvedValueOnce(unauth());
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await load();
    const err = await api("/inbox").catch((e) => e);
    expect(err.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("maps a 5xx to a retryable ApiError and a 4xx to a non-retryable one", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json(503, { detail: "down" }))
      .mockResolvedValueOnce(json(422, { detail: "bad" })));
    const { api } = await load();
    const a = await api("/x").catch((e) => e);
    const b = await api("/x").catch((e) => e);
    expect(a.retryable).toBe(true);
    expect(b.retryable).toBe(false);
    expect(b.message).toBe("bad");
  });

  it("returns null for 204", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 204, json: async () => { throw new Error("no body"); } })));
    const { api } = await load();
    await expect(api("/x", { method: "DELETE" })).resolves.toBeNull();
  });
});

describe("refresh timeout", () => {
  it("a hung /auth/refresh surfaces as a retryable timeout, not a hang", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "expired" } }))
      .mockImplementationOnce((_u, init) => new Promise((_r, reject) => {
        init.signal.addEventListener("abort", () => reject(Object.assign(new Error("a"), { name: "AbortError" })));
      }));
    vi.stubGlobal("fetch", fetchMock);
    const { api, REQUEST_TIMEOUT_MS } = await load();
    const pending = api("/inbox").catch((e) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    const err = await pending;
    expect(err.code).toBe("timeout");
    expect(err.retryable).toBe(true);
  });
});

describe("publicApi() timeout", () => {
  it("times out a hung login request", async () => {
    vi.stubGlobal("fetch", hangingFetch());
    const { publicApi, REQUEST_TIMEOUT_MS } = await load();
    const pending = publicApi("/auth/login", { body: { email: "a", password: "b" } }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    expect((await pending).code).toBe("timeout");
  });

  it("still maps a network failure to code 'network'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const { publicApi } = await load();
    expect((await publicApi("/auth/login", { body: {} }).catch((e) => e)).code).toBe("network");
  });
});

describe("apiCached()", () => {
  it("serves a fresh hit without a second request, and refetches after a mutation", async () => {
    const fetchMock = vi.fn(async () => json(200, { n: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    const { api, apiCached } = await load();
    await apiCached("/analytics/summary");
    await apiCached("/analytics/summary");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await api("/conversations/1/read", { method: "POST" });
    await apiCached("/analytics/summary");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("dedupes concurrent calls for the same path into one request", async () => {
    const fetchMock = vi.fn(async () => json(200, { n: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    const { apiCached } = await load();
    await Promise.all([apiCached("/ai/agents"), apiCached("/ai/agents"), apiCached("/ai/agents")]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
