"use client";

/** API client: token storage, refresh-on-401, typed helpers.
 *  Tokens live in localStorage (staff dashboard, not a public surface). */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Tokens = { access_token: string; refresh_token: string };

export function getTokens(): Tokens | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("sales_os_tokens");
  return raw ? (JSON.parse(raw) as Tokens) : null;
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
    const res = await fetch(`${API}/auth/refresh`, {
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
  options: { method?: string; body?: unknown; retry?: boolean } = {},
): Promise<T> {
  const tokens = getTokens();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (tokens?.access_token) headers["Authorization"] = `Bearer ${tokens.access_token}`;

  const res = await fetch(`${API}${path}`, {
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

export const API_BASE_URL = API;
