import { useCallback, useEffect, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";

/** استهلاك الذكاء الحقيقي من GET /ai/usage/summary — بتاع واحد UTC
 *  وإجماليات الفترة. بيرجع null أثناء التحميل. */
export default function useUsageSummary() {
  const [data, setData] = useState(() => peekCache("/ai/usage/summary") || null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((current) => current + 1), []);

  useEffect(() => {
    let alive = true;
    const cached = peekCache("/ai/usage/summary");
    if (cached) setData(cached);
    setError("");
    apiCached("/ai/usage/summary")
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError("");
      })
      .catch((e) => alive && setError(e?.message || "Could not load AI usage"));
    return () => {
      alive = false;
    };
  }, [attempt]);

  return data ? { ...data, error, retry } : error ? { totals: null, error, retry } : null;
}
