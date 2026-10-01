import { useCallback, useEffect, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";

/** الموافقات المعلّقة الحقيقية من GET /ai/approvals. بيرجع null أثناء
 *  التحميل. الفلوس والقرارات بتتقرأ من الـbackend — مفيش بيانات محلية. */
export default function useApprovals(status = "PENDING") {
  const [data, setData] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((current) => current + 1), []);

  useEffect(() => {
    let alive = true;
    const path = `/ai/approvals?status=${encodeURIComponent(status)}`;
    const cached = peekCache(path);
    if (cached) setData({ ...cached, error: null });
    apiCached(path)
      .then((d) => alive && setData({ ...d, error: null }))
      .catch((error) => alive && setData({ items: [], truncated: false, error: error?.message || "Could not load approvals" }));
    return () => {
      alive = false;
    };
  }, [status, attempt]);

  return data ? { ...data, retry } : null;
}
