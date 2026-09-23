"use client";

/** نداءات المصادقة — متوافقة مع إصداري الـbackend:
 *  المنشور حاليًا يخدم /auth/* مباشرة، والإصدار الأحدث يخدمها تحت /api/v1.
 *  نجرّب المسار الجديد أولًا، ونتراجع للقديم عند 404 (مسار غير موجود فقط).
 *
 *  ملاحظة: في الإنتاج، تستهلك الطلبات عبر Vercel rewrite (نفس الـorigin) لتفادي
 *  قيود CORS. أثناء التطوير المحلي، `NEXT_PUBLIC_API_URL` يجب أن يشير للـbackend.
 *
 *  قاعدة بناء العنوان ليست مكررة هنا: `api.apiUrl` هي المصدر الوحيد (كانت هذه
 *  الملف يحسب BASE بنفسه — نسخة ثانية من نفس القاعدة هي ما أبقى /api/v1/api/v1
 *  حيًّا في ملفٍ آخر؛ راجع scripts/check-request-urls.mjs). */

import { API_BASE_URL, apiUrl } from "@/lib/api";

type AuthOk<T> = { ok: true; data: T };
type AuthFail = { ok: false; status: number; message?: string };
export type AuthResult<T> = AuthOk<T> | AuthFail;

export async function authPost<T = unknown>(
  path: string,
  body: unknown,
): Promise<AuthResult<T>> {
  const headers = { "Content-Type": "application/json" };
  const payload = JSON.stringify(body);

  let res = await fetch(apiUrl(path), {
    method: "POST",
    headers,
    body: payload,
  });
  if (res.status === 404 && !API_BASE_URL.startsWith("/")) {
    // fallback to legacy path shape (no /api/v1 prefix) — only when not proxied.
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
      const raw = data?.error?.message ?? data?.detail;
      if (typeof raw === "string" && raw) message = raw;
    } catch {
      /* بدون جسم JSON */
    }
    return { ok: false, status: res.status, message };
  }
  return { ok: true, data: (await res.json()) as T };
}