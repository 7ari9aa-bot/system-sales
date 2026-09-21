"use client";

/** API client: token storage, refresh-on-401, typed helpers.
 *  Tokens live in localStorage (staff dashboard, not a public surface). */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Versioned API prefix — every path is relative to it (/api/v1/...). */
export const API_PREFIX = "/api/v1";

type Tokens = { access_token: string; refresh_token: string };

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
    const res = await fetch(`${API}${API_PREFIX}/auth/refresh`, {
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
  options: {
    method?: string;
    body?: unknown;
    retry?: boolean;
    /** §91: pass an Idempotency-Key on POST/PUT so a retried request does not double-write. */
    idempotencyKey?: string;
    /** §17: pass If-Match with the aggregate's version for optimistic locking. */
    ifMatch?: string | number;
  } = {},
): Promise<T> {
  const tokens = getTokens();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (tokens?.access_token) headers["Authorization"] = `Bearer ${tokens.access_token}`;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  if (options.ifMatch !== undefined) headers["If-Match"] = String(options.ifMatch);

  const res = await fetch(`${API}${API_PREFIX}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401 && options.retry !== false) {
    const refreshed = await tryRefresh();
    if (refreshed) return api<T>(path, { ...options, retry: false });
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("غير مصرّح");
  }

  if (!res.ok) {
    let message = `خطأ ${res.status}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** §91: generate a random Idempotency-Key for safe-retry POSTs. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export const API_BASE_URL = API;
