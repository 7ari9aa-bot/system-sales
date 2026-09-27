"use client";

/** API client: token storage, refresh-on-401/403, typed helpers.
 *  Tokens live in localStorage (staff dashboard, not a public surface). */

const API = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

/** Versioned API prefix — every path is relative to it (/api/v1/...). */
export const API_PREFIX = "/api/v1";

/** One route path in, one request URL out.
 *
 *  The base has two shapes. Same-origin (the default: `NEXT_PUBLIC_API_URL`
 *  unset, so `API` is already `/api/v1` and Next rewrites it to the API) must
 *  NOT gain the prefix again; an absolute origin has none and must. Both used to
 *  be spelled out at each call site, and two of them — the 401 refresh and the
 *  logout ping — appended the prefix unconditionally, so under the DEFAULT shape
 *  they asked for `/api/v1/api/v1/...`. A 404 refresh reads as "the session is
 *  gone", which logs the staff out on the first expired token. Anything that
 *  builds a URL asks this function instead. */
export function apiUrl(path: string): string {
  const rel = path.startsWith(API_PREFIX) ? path.slice(API_PREFIX.length) : path;
  return API.startsWith("/") ? `${API}${rel}` : `${API}${API_PREFIX}${rel}`;
}

/** `apiUrl()` resolved against the origin of the document making the call.
 *
 *  Under the default same-origin shape `apiUrl()` answers with a RELATIVE path
 *  (`/api/v1/...`) — that is the point of it, and `check-request-urls.mjs`
 *  asserts it. Most consumers never mind: `fetch` resolves a relative URL
 *  against the document. The URL CONSTRUCTOR does not: it requires an absolute
 *  argument, so feeding it `apiUrl()` directly throws
 *  `TypeError: Invalid URL` in the browser while type-checking and building
 *  cleanly. Anything that needs an absolute URL — a `URL` to put query
 *  parameters on, a link that leaves the document — asks this and passes the
 *  origin it is standing in. Under the absolute-base shape the base is already
 *  absolute and `origin` is ignored, exactly as the URL spec says.
 *
 *  Never call it at module scope with `window.location.origin`: a client module
 *  is still evaluated on the server during prerender, where `window` does not
 *  exist. Resolve at the moment of use. */
export function absoluteApiUrl(path: string, origin: string): string {
  return new URL(apiUrl(path), origin).toString();
}

type Tokens = { access_token: string; refresh_token: string };

/** The unified API error envelope (`app/core/errors.build_error_body`). */
type ErrorEnvelope = {
  error?: { code?: string; message?: string; retryable?: boolean };
  detail?: unknown;
};

/** Response header the idempotency guard sets when it replays a stored answer
 *  instead of re-running the request (`core/idempotency.REPLAY_HEADER`). */
export const IDEMPOTENCY_REPLAY_HEADER = "Idempotency-Replayed";

/** An HTTP failure that keeps the status and the machine code.
 *
 *  The plain `Error` the client used to throw erased the status, so no call
 *  site could tell a 409 idempotency conflict (the write already happened, or
 *  the guard refused to re-run it) from a 400 it may fix and resend. Those two
 *  need opposite behavior, so the status has to survive the throw. It still
 *  extends `Error` and carries the same message, so every existing
 *  `err instanceof Error` / `err.message` consumer keeps working untouched. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;

  constructor(message: string, init: { status: number; code?: string | null; retryable?: boolean }) {
    super(message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code ?? null;
    this.retryable = init.retryable ?? false;
  }
}

/** True when a request failed with 409 CONFLICT.
 *
 *  Deliberately narrow, and deliberately not "409 AND the message says
 *  Idempotency": `ConflictError` (business conflict: a blocked customer, a
 *  tenant-currency mismatch, a stale `If-Match`) and the idempotency guard
 *  share the `conflict` code and the 409 status. Either way the rule for the
 *  caller is the same — the attempt is over, the client must NOT mint a new key
 *  and fire the same write again, because it may already have landed. */
export function isConflictError(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 409;
}

export type ApiRequestOptions = {
  method?: string;
  body?: unknown;
  retry?: boolean;
  /** §91: pass an Idempotency-Key on POST/PUT so a retried request does not double-write. */
  idempotencyKey?: string;
  /** §17: pass If-Match with the aggregate's version for optimistic locking. */
  ifMatch?: string | number;
};

/** A response with the metadata `api()` drops. */
export type ApiResponse<T> = {
  data: T;
  status: number;
  /** The guard replayed a stored answer: nothing ran server-side this time.
   *  Cross-origin callers may read `false` even on a replay — a custom
   *  response header is only visible to the browser if the API lists it in
   *  `Access-Control-Expose-Headers`, and `app.main` sets `allow_headers` but
   *  no `expose_headers`. Treat it as a hint, never as proof. */
  replayed: boolean;
};

export function getTokens(): Tokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("sales_os_tokens");
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Tokens;
    return parsed?.access_token ? parsed : null;
  } catch {
    // Malformed stored value: treat as logged out instead of bricking the app.
    window.localStorage.removeItem("sales_os_tokens");
    return null;
  }
}

export function setTokens(t: Tokens | null) {
  if (typeof window === "undefined") return;
  if (t) window.localStorage.setItem("sales_os_tokens", JSON.stringify(t));
  else window.localStorage.removeItem("sales_os_tokens");
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const tokens = getTokens();
    if (!tokens?.refresh_token) return false;
    const res = await fetch(apiUrl("/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: tokens.refresh_token }),
    });
    if (!res.ok) {
      setTokens(null);
      return false;
    }
    const pair = (await res.json()) as Tokens;
    setTokens({ access_token: pair.access_token, refresh_token: pair.refresh_token });
    return true;
  })();
  try {
    return await refreshing;
  } finally {
    refreshing = null;
  }
}

export async function api<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const res = await apiWithMeta<T>(path, options);
  return res.data;
}

/** `api()` plus the two things a guarded write needs back: the status it came
 *  in on, and whether the idempotency guard replayed an older answer instead of
 *  running the request. Every call site that only wants the body keeps using
 *  `api()`, which is this function with the envelope unwrapped. */
export async function apiWithMeta<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<ApiResponse<T>> {
  const tokens = getTokens();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (tokens?.access_token) headers["Authorization"] = `Bearer ${tokens.access_token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  if (options.ifMatch !== undefined) headers["If-Match"] = String(options.ifMatch);

  const url = apiUrl(path);
  const res = await fetch(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  const replayed = res.headers.get(IDEMPOTENCY_REPLAY_HEADER) === "true";

  if (res.status === 401 && options.retry !== false) {
    const refreshed = await tryRefresh();
    // The SAME key goes out again — a refreshed token is still the same user
    // intent, and replaying it against a completed write is the point.
    if (refreshed) return apiWithMeta<T>(path, { ...options, retry: false });
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError("غير مصرّح", { status: 401, code: "unauthorized" });
  }

  // The backend uses PermissionDeniedError (HTTP 403) for expired / invalid
  // tokens as well as genuine permission denials. Only trigger refresh if the
  // error message specifically indicates a token issue.
  if (res.status === 403 && options.retry !== false) {
    try {
      const cloned = res.clone();
      const body = (await cloned.json()) as ErrorEnvelope;
      const raw = body?.error?.message ?? body?.detail;
      const msg = typeof raw === "string" ? raw.toLowerCase() : "";
      if (msg.includes("token") || msg.includes("bearer")) {
        const refreshed = await tryRefresh();
        if (refreshed) return apiWithMeta<T>(path, { ...options, retry: false });
        if (typeof window !== "undefined") window.location.href = "/login";
        throw new ApiError("غير مصرّح", { status: 401, code: "unauthorized" });
      }
    } catch (e) {
      if (e instanceof ApiError) throw e;
    }
  }

  if (!res.ok) {
    let message = `خطأ ${res.status}`;
    let code: string | null = null;
    let retryable = false;
    try {
      const body = (await res.json()) as ErrorEnvelope;
      // Same precedence as before: the envelope's message, then FastAPI's
      // `detail`, then the status fallback. `detail` is `unknown` (a 422
      // validation error carries an array), so it is stringified exactly the
      // way `new Error(...)` used to coerce it rather than assumed to be text.
      const raw = body?.error?.message ?? body?.detail;
      if (typeof raw === "string") message = raw;
      else if (raw !== null && raw !== undefined) message = String(raw);
      code = typeof body?.error?.code === "string" ? body.error.code : null;
      retryable = body?.error?.retryable === true;
    } catch {
      /* keep default */
    }
    throw new ApiError(message, { status: res.status, code, retryable });
  }
  if (res.status === 204) return { data: undefined as T, status: res.status, replayed };
  return { data: (await res.json()) as T, status: res.status, replayed };
}

/** §91: generate a random Idempotency-Key for safe-retry POSTs. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export const API_BASE_URL = API;

/**
 * Object-oriented wrapper for pages that prefer `apiClient.get(...)` style.
 * Paths already include `/api/v1` prefix internally, so callers pass full paths
 * like `/api/v1/team/members`.
 */
function buildPath(path: string): string {
  // If the caller already includes /api/v1, strip it so we don't double-prefix.
  if (path.startsWith(API_PREFIX)) return path.slice(API_PREFIX.length);
  return path;
}

export const apiClient = {
  get: <T = unknown>(path: string) => api<T>(buildPath(path)),
  post: <T = unknown>(path: string, body?: unknown) =>
    api<T>(buildPath(path), { method: "POST", body }),
  patch: <T = unknown>(path: string, body?: unknown) =>
    api<T>(buildPath(path), { method: "PATCH", body }),
  put: <T = unknown>(path: string, body?: unknown) =>
    api<T>(buildPath(path), { method: "PUT", body }),
  delete: <T = unknown>(path: string) =>
    api<T>(buildPath(path), { method: "DELETE" }),
};
