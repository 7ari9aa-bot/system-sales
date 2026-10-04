/** عميل الـAPI الحقيقي — بيتكلم مع الـFastAPI backend (نفس عقود /api/v1).
 *  التوكنات في localStorage مع refresh تلقائي عند 401.
 *  الفلوس بتوصل نصوص Decimal فلازم تتطبع زي ما هي — مفيش floats. */

/** نظام الحارس — ضد الأخطاء الصامتة (مراجع نصي: lib/guardian.js). */
import { guardianReport } from "./guardian";

const API = import.meta.env.VITE_API_URL ?? "/api/v1";

export const API_PREFIX = "/api/v1";

export function apiUrl(path) {
  const rel = path.startsWith(API_PREFIX) ? path.slice(API_PREFIX.length) : path;
  if (API.startsWith("/")) {
    const base = API.replace(/\/+$/, "");
    const apiPath = base.endsWith(API_PREFIX) ? base : `${base}${API_PREFIX}`;
    return `${apiPath}${rel}`;
  }
  const parsed = new URL(API, window.location.origin);
  const basePath = parsed.pathname.replace(/\/+$/, "");
  const apiPath = basePath.endsWith(API_PREFIX) ? basePath : `${basePath}${API_PREFIX}`;
  return `${parsed.origin}${apiPath}${rel}`;
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
  // Never let a response cached under one session survive a session change.
  invalidateCache();
}

export class ApiError extends Error {
  constructor(message, { status = 0, code = null, retryable = false, details = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.details = details;
  }
}

/** Public auth requests intentionally omit a saved bearer token and refresh. */
export async function publicApi(path, { method = "POST", body } = {}) {
  let res;
  try {
    res = await fetch(apiUrl(path), {
      method,
      cache: "no-store",
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new ApiError("تعذّر الوصول إلى الخادم (شبكة)", {
      status: 0,
      code: "network",
      retryable: true,
    });
  }

  if (res.status === 204) return null;
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* Empty/non-JSON responses are handled by the status below. */
  }
  if (!res.ok) {
    const raw = data?.error?.message ?? data?.detail;
    throw new ApiError(typeof raw === "string" ? raw : `HTTP ${res.status}`, {
      status: res.status,
      code: data?.error?.code ?? null,
      retryable: data?.error?.retryable ?? res.status >= 500,
      details: data?.error?.details ?? data?.details ?? null,
    });
  }
  return data;
}

let refreshInFlight = null;

// The production API currently serializes missing/invalid bearer credentials
// as 403 `permission_denied`. Keep this compatibility mapping narrow so real
// role/permission denials remain 403 and do not trigger a token refresh.
const AUTHENTICATION_DENIAL_MESSAGES = new Set([
  "missing bearer token",
  "wrong token type",
  "invalid token",
  "account is inactive",
  "session revoked by password reset",
]);

function isAuthenticationFailure(status, code, message) {
  if (status === 401 || code === "unauthorized") return true;
  return status === 403
    && code === "permission_denied"
    && AUTHENTICATION_DENIAL_MESSAGES.has(String(message ?? "").trim().toLowerCase());
}

async function refreshTokens() {
  if (refreshInFlight) return refreshInFlight;
  const task = (async () => {
    const tokens = getTokens();
    if (!tokens?.refresh_token) return false;
    let res;
    try {
      res = await fetch(apiUrl("/auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
    } catch {
      throw new ApiError("تعذّر تجديد الجلسة بسبب مشكلة في الشبكة", {
        status: 0,
        code: "network",
        retryable: true,
      });
    }
    if (res.status >= 500) {
      throw new ApiError(`تعذّر تجديد الجلسة (HTTP ${res.status})`, {
        status: res.status,
        code: "refresh_unavailable",
        retryable: true,
      });
    }
    if (!res.ok) return false;
    try {
      const data = await res.json();
      if (!data?.access_token) return false;
      setTokens({ access_token: data.access_token, refresh_token: data.refresh_token ?? tokens.refresh_token });
      return true;
    } catch {
      throw new ApiError("استجابة تجديد الجلسة غير صالحة", {
        status: res.status,
        code: "refresh_response_invalid",
        retryable: true,
      });
    }
  })();
  refreshInFlight = task;
  try {
    return await task;
  } finally {
    if (refreshInFlight === task) refreshInFlight = null;
  }
}

/** نداء API عام — يرمي ApiError، ويجدد التوكن مرة واحدة عند انتهائه. */
export async function api(path, { method = "GET", body, retry = true, headers = {} } = {}) {
  const tokens = getTokens();
  let res;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(tokens?.access_token ? { Authorization: `Bearer ${tokens.access_token}` } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (networkErr) {
    // فشل الشبكة (الخادم وايقف، انقطاع نت، اعتراض) — أخطر أنواع الفشل
    // الصامت لأن مفيش status أصلاً: لازم يتسجل زي أي قراءة فاشلة.
    const err = new ApiError("تعذّر الوصول إلى الخادم (شبكة)", {
      status: 0,
      code: "network",
      retryable: true,
    });
    if (method === "GET" && !path.startsWith("/auth/")) reportFailure(path, err);
    throw err;
  }

  let errorMessage = `HTTP ${res.status}`;
  let errorCode = null;
  let errorDetails = null;
  if (!res.ok) {
    try {
      const data = await res.json();
      const raw = data?.error?.message ?? data?.detail;
      if (typeof raw === "string") errorMessage = raw;
      errorCode = data?.error?.code ?? null;
      errorDetails = data?.error?.details ?? data?.details ?? null;
    } catch {
      /* بدون جسم JSON */
    }
  }

  const authenticationFailure = isAuthenticationFailure(res.status, errorCode, errorMessage);
  const inactiveAccount = errorMessage.trim().toLowerCase() === "account is inactive";

  if (authenticationFailure && retry && tokens?.refresh_token && !inactiveAccount) {
    let ok;
    try {
      ok = await refreshTokens();
    } catch (refreshError) {
      const current = getTokens();
      if (current?.access_token && current.access_token !== tokens.access_token) {
        return api(path, { method, body, retry: false, headers });
      }
      if (method === "GET" && !path.startsWith("/auth/")) reportFailure(path, refreshError);
      throw refreshError;
    }
    if (ok) return api(path, { method, body, retry: false, headers });
    const current = getTokens();
    if (current?.access_token && current.access_token !== tokens.access_token) {
      return api(path, { method, body, retry: false, headers });
    }
    setTokens(null);
  }

  // Missing credentials, a rejected refresh token, or an inactive account
  // must become a terminal auth state. AuthContext handles 401/unauthorized
  // by clearing the session and returning the user to the login route.
  if (authenticationFailure && (!retry || !tokens?.refresh_token || inactiveAccount)) {
    setTokens(null);
  }

  if (!res.ok) {
    // قاعدة الحارس: أي قراءة (GET) فاشلة برا مسار المصادقة مش بتنطّي —
    // بتتسجل في الحارس حتى لو المُستهلك قبض الخطأ وعرض صفير فاضي.
    // فشل المصادقة المتوقع (بيانات دخول غلط) بيتعرض في الفورم نفسه.
    const err = new ApiError(errorMessage, {
      status: authenticationFailure ? 401 : res.status,
      code: authenticationFailure ? "unauthorized" : errorCode,
      retryable: res.status >= 500,
      details: errorDetails,
    });
    if (method === "GET" && !path.startsWith("/auth/")) {
      reportFailure(path, err);
    }
    throw err;
  }
  const data = res.status === 204 ? null : await res.json();
  // Mutations can change any derived dashboard view. Clear cached reads so the
  // next screen load cannot present the pre-mutation value as current.
  if (method !== "GET") invalidateCache();
  return data;
}

/* ---------------------------------------------------------- الكاش اللحظي */

/** كاش بمدة صلاحية في الذاكرة: الاستجابة الحديثة تُستخدم مباشرة، وبعد
 *  انتهاء المدة يبدأ طلب جديد. النداءات المتزامنة لنفس المسار تتجمع
 *  في طلب واحد (in-flight dedupe). */
const cache = new Map(); // path -> { data, at }
const inflight = new Map(); // path -> Promise
let cacheGeneration = 0;

export const DEFAULT_TTL_MS = 20_000;

/** الفشل في أي قراءة بيتسجل في الحارس قبل ما يرجع للمُستهلك —
 *  الـhooks اللي بتقبض الخطأ في catch بتاعها مش بتقدر تخفيه. */
function reportFailure(path, err) {
  guardianReport({
    kind: "api",
    source: path,
    message: err?.message || String(err),
  });
}

/** تبليغ عن فشل خلفي — طلبات الـprefetch وإعادة التحقق اللي بتشتغل
 *  ورا ظهر الكاش. المُستهلك مش شايف الطلب ده أصلًا، فلو فشل لازم
 *  يوصل للحارس بدل ما ينطّي من غير أي أثر. فيها تهدئة لكل مسار:
 *  مسار بيفشل مرار في حلقة ضيقة بيتبلّغ مرة واحدة في النافذة، عشان
 *  الكونسول وشارة الحارس ما يغرقوش في تكرار لنفس الخبر. التبليغ هنا
 *  طبقة ضمان مش اعتماد على شروط التسجيل جوة الدالة api نفسها،
 *  فأي فشل بيعدي من هنا حتى لو اتغيرت شروط التسجيل دي، والحارس
 *  بيدمج الأحداث المكررة لوحده فمفيش ضغط على الشارة. */
const BACKGROUND_REPORT_COOLDOWN_MS = 30_000;
const backgroundReportAt = new Map(); // path -> last report timestamp

function reportBackgroundFailure(path, err) {
  const now = Date.now();
  if (now - (backgroundReportAt.get(path) ?? 0) < BACKGROUND_REPORT_COOLDOWN_MS) return;
  backgroundReportAt.set(path, now);
  reportFailure(path, err);
}

export function invalidateCache(prefix) {
  // A pre-mutation GET may still be pending. Invalidate its generation and
  // detach it so the next consumer starts a fresh request instead of reusing
  // the old promise. The older promise may finish, but cannot repopulate cache.
  cacheGeneration += 1;
  for (const key of cache.keys()) {
    if (!prefix || key.startsWith(prefix)) cache.delete(key);
  }
  for (const key of inflight.keys()) {
    if (!prefix || key.startsWith(prefix)) inflight.delete(key);
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
  for (const p of paths) {
    // الـprefetch خلفي بحت: فشله مينفعش يكسر التحميل الأولي للبيانات،
    // بس لازم يتشاف — التبليغ بيمر على الحارس بتهدئة لكل مسار.
    apiCached(p).catch((err) => reportBackgroundFailure(p, err));
  }
}

export function apiCached(path, { ttlMs = DEFAULT_TTL_MS } = {}) {
  const hit = cache.get(path);
  const fresh = hit && Date.now() - hit.at < ttlMs;

  // Do not start a background request for a cache hit: callers receive the
  // cached value immediately and otherwise cannot observe that revalidation.
  if (fresh) return Promise.resolve(hit.data);
  if (inflight.has(path)) return inflight.get(path);

  const generation = cacheGeneration;
  const promise = (async () => {
    const data = await api(path);
    if (generation === cacheGeneration) cache.set(path, { data, at: Date.now() });
    return data;
  })();

  inflight.set(path, promise);
  promise.finally(() => {
    if (inflight.get(path) === promise) inflight.delete(path);
  }).catch((err) => reportBackgroundFailure(path, err));

  // The caller receives fresh server data whenever the cached response expires.
  return promise;
}
