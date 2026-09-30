import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** استهلاك الذكاء الحقيقي من GET /ai/usage/summary — بتاع واحد UTC
 *  وإجماليات الفترة. بيرجع null أثناء التحميل. */
export default function useUsageSummary() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    api("/ai/usage/summary")
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, []);

  return data;
}
