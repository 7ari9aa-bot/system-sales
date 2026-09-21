"use client";

/** نداءات المصادقة — متوافقة مع إصداري الـbackend:
 *  المنشور حاليًا يخدم /auth/* مباشرة، والإصدار الأحدث يخدمها تحت /api/v1.
 *  نجرّب المسار الجديد أولًا، ونتراجع للقديم عند 404 (مسار غير موجود فقط).
 *
 *  ملاحظة: في الإنتاج، تستهلك الطلبات عبر Vercel rewrite (نفس الـorigin) لتفادي
 *  قيود CORS. أثناء التطوير المحلي، `NEXT_PUBLIC_API_URL` يجب أن يشير للـbackend. */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

function buildUrl(path: string): string {
  // خلال Vercel rewrite: BASE = "/api/v1" في الإنتاج. نضيف /api/v1 قبل المسار.
  // في dev: BASE = "http://localhost:8000"، نضيف /api/v1 كذلك للاتساق.
  if (BASE.startsWith("/")) {
    // Path-based (same-origin via rewrite). Already include /api/v1.
    return `${BASE}${path}`;
  }
  return `${BASE}/api/v1${path}`;
}

type AuthOk<T> = { ok: true; data: T };
type AuthFail = { ok: false; status: number; message?: string };
export type AuthResult<T> = AuthOk<T> | AuthFail;

export async function authPost<T = unknown>(
  path: string,
  body: unknown,
): Promise<AuthResult<T>> {
  const headers = { "Content-Type": "application/json" };
  const payload = JSON.stringify(body);

  let res = await fetch(buildUrl(path), {
    method: "POST",
    headers,
    body: payload,
  });
  if (res.status === 404 && !BASE.startsWith("/")) {
    // fallback to legacy path shape (no /api/v1 prefix) — only when not proxied.
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers,
      body: payload,
    });
  }

  if (!res.ok) {
    let message: string | undefined;
    try {
      const data = await res.json();
      const raw = data?.error?.message ?? data?.detail;
      if (typeof raw === "string" && raw) message = raw;
    } catch {
      /* بدون جسم JSON */
    }
    return { ok: false, status: res.status, message };
  }
  return { ok: true, data: (await res.json()) as T };
}