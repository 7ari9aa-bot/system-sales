"use client";

/**
 * ApiErrorInterceptor — Anti-Silent-Failures global error surface.
 *
 * Listens on `window` for `api-error` CustomEvents dispatched by `api.ts` on
 * 5xx / network failures. Renders a toast with the exact error message and
 * request ID so no server failure goes unnoticed, even if the calling hook has
 * no `onError` handler.
 *
 * Mount once inside `Providers` — it is invisible (renders nothing) and only
 * fires toasts when something breaks.
 */

import { useEffect } from "react";
import { toast } from "@/components/ui/toast";

type ApiErrorDetail = {
  message?: string;
  status?: number;
  code?: string | null;
  requestId?: string | null;
  path?: string;
};

export function ApiErrorInterceptor() {
  useEffect(() => {
    function handleApiError(e: Event) {
      const detail = (e as CustomEvent<ApiErrorDetail>).detail;
      if (!detail) return;

      const title = `خطأ في الخادم (${detail.status ?? "غير معروف"})`;
      const parts: string[] = [];
      if (detail.message) parts.push(detail.message);
      if (detail.requestId) parts.push(`معرّف الطلب: ${detail.requestId}`);
      if (detail.path) parts.push(`المسار: ${detail.path}`);

      toast({
        title,
        description: parts.join("\n") || "حدث خطأ غير متوقع في الخادم",
        variant: "danger",
        duration: 8000,
      });
    }

    window.addEventListener("api-error", handleApiError);
    return () => window.removeEventListener("api-error", handleApiError);
  }, []);

  return null;
}
