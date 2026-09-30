/** عميل الـAPI الحقيقي — بيتكلم مع الـFastAPI backend (نفس عقود /api/v1).
 *  التوكنات في localStorage مع refresh تلقائي عند 401/403.
 *  الفلوس بتوصل نصوص Decimal فلازم تتطبع زي ما هي — مفيش floats. */

const API = import.meta.env.VITE_API_URL ?? "/api/v1";

export const API_PREFIX = "/api/v1";

export function apiUrl(path) {
  const rel = path.startsWith(API_PREFIX) ? path.slice(API_PREFIX.length) : path;
  return API.startsWith("/") ? `${API}${rel}` : `${API}${API_PREFIX}${rel}`;
}

const TOKENS_KEY = "fihrist_tokens";

export function getTokens() {
  try {
    const raw = window.localStorage.getItem(TOKENS_KEY);
    if (!raw) return null;
    const t = JSON.parse(raw);
    return t?.access_token && t?.refresh_token ? t : null;
  } catch {
    return null;
  }
}

export function setTokens(tokens) {
  try {
    if (tokens) window.localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
    else window.localStorage.removeItem(TOKENS_KEY);
  } catch {
    /* private mode */
  }
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = null, retryable = false } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

async function refreshTokens() {
  const tokens = getTokens();
  if (!tokens?.refresh_token) return false;
  const res = await fetch(apiUrl("/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  if (!data?.access_token) return false;
  setTokens({ access_token: data.access_token, refresh_token: data.refresh_token ?? tokens.refresh_token });
  return true;
}

/** نداء API عام — يرمي ApiError، ويجدد التوكن مرة واحدة عند انتهائه. */
export async function api(path, { method = "GET", body, retry = true, headers = {} } = {}) {
  const tokens = getTokens();
  const res = await fetch(apiUrl(path), {
    method,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(tokens?.access_token ? { Authorization: `Bearer ${tokens.access_token}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });

  if ((res.status === 401 || res.status === 403) && retry && tokens?.refresh_token) {
    const ok = await refreshTokens();
    if (ok) return api(path, { method, body, retry: false, headers });
    setTokens(null);
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    let code = null;
    try {
      const data = await res.json();
      const raw = data?.error?.message ?? data?.detail;
      if (typeof raw === "string") message = raw;
      code = data?.error?.code ?? null;
    } catch {
      /* بدون جسم JSON */
    }
    throw new ApiError(message, { status: res.status, code, retryable: res.status >= 500 });
  }
  if (res.status === 204) return null;
  return res.json();
}

/* ---------------------------------------------------------- الكاش اللحظي */

/** كاش stale-while-revalidate في الميموري: البيانات بتترسم من الكاش
 *  في أجزاء من الثانية على أي تنقل، والتحديث بيحصل صامت في الخلفية.
 *  النداءات المتكررة لنفس المسار بتتجمع في نداء واحد (in-flight dedupe). */
const cache = new Map(); // path -> { data, at }
const inflight = new Map(); // path -> Promise

export const DEFAULT_TTL_MS = 20_000;

export function invalidateCache(prefix) {
  for (const key of cache.keys()) {
    if (!prefix || key.startsWith(prefix)) cache.delete(key);
  }
}

/** قراءة لحظية من الكاش — بترجع data أو null. */
export function peekCache(path) {
  return cache.get(path)?.data ?? null;
}

export function prefetchDashboard() {
  const paths = [
    "/analytics/dashboard",
    "/analytics/overview?days=30",
    "/ai/usage/summary",
    "/ai/approvals?status=PENDING",
    "/ai/agents",
    "/marketing/campaigns",
    "/analytics/summary",
  ];
  for (const p of paths) void apiCached(p);
}

export function apiCached(path, { ttlMs = DEFAULT_TTL_MS } = {}) {
  const hit = cache.get(path);
  const fresh = hit && Date.now() - hit.at < ttlMs;

  if (inflight.has(path)) return inflight.get(path);

  const promise = (async () => {
    const data = await api(path);
    cache.set(path, { data, at: Date.now() });
    return data;
  })();

  inflight.set(path, promise);
  promise.finally(() => inflight.delete(path)).catch(() => {});

  // stale-while-revalidate: القديمة بترجع فورًا والجديدة بتوصل بعدها
  if (fresh) return hit.data;
  if (hit) {
    return promise.then((data) => data);
  }
  return promise;
}

