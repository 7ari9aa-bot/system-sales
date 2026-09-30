import { useEffect, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";

/** الموافقات المعلّقة الحقيقية من GET /ai/approvals. بيرجع null أثناء
 *  التحميل. الفلوس والقرارات بتتقرأ من الـbackend — مفيش بيانات محلية. */
export default function useApprovals(status = "PENDING") {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    const path = `/ai/approvals?status=${encodeURIComponent(status)}`;
    const cached = peekCache(path);
    if (cached) setData(cached);
    apiCached(path)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData({ items: [], truncated: false }));
    return () => {
      alive = false;
    };
  }, [status]);

  return data;
}
