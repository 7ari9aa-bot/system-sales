"use client";

import { API_BASE_URL } from "@/lib/api";

/** نداءات المصادقة — متوافقة مع إصداري الـbackend:
 *  المنشور حاليًا يخدم /auth/* مباشرة، والإصدار الأحدث يخدمها تحت /api/v1.
 *  نجرّب المسار الجديد أولًا، ونتراجع للقديم عند 404 (مسار غير موجود فقط). */

type AuthOk<T> = { ok: true; data: T };
type AuthFail = { ok: false; status: number; message?: string };
export type AuthResult<T> = AuthOk<T> | AuthFail;

export async function authPost<T = unknown>(
  path: string,
  body: unknown,
): Promise<AuthResult<T>> {
  const headers = { "Content-Type": "application/json" };
  const payload = JSON.stringify(body);

  let res = await fetch(`${API_BASE_URL}/api/v1${path}`, {
    method: "POST",
    headers,
    body: payload,
  });
  if (res.status === 404) {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers,
      body: payload,
    });
  }

  if (!res.ok) {
    let message: string | undefined;
    try {
      const data = await res.json();
      message = data?.error?.message ?? data?.detail;
    } catch {
      /* بدون جسم JSON */
    }
    return { ok: false, status: res.status, message };
  }
  return { ok: true, data: (await res.json()) as T };
}
