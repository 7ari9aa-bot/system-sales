import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** بيانات استخدام حقيقية من الـbackend:
 *  - USAGE: استهلاك الذكاء من /ai/usage/summary. الـbackend مش بينشر
 *    «خطة» ولا «حدود باقة» ولا عدد المحادثات المسموحة — فالقيم دي
 *    بترجع null والشاشات بتخفيها بدل ما تعرض حدود وهمية.
 *  - CHANNELS: حالة القنوات الحقيقية من /integrations. */

let cachedUsage = null;
let cachedChannels = null;

export function useRealUsage() {
  const [usage, setUsage] = useState(cachedUsage);
  useEffect(() => {
    if (cachedUsage) return;
    let alive = true;
    api("/ai/usage/summary")
      .then((d) => {
        if (!alive) return;
        const totals = d?.totals ?? null;
        const tokens = totals ? (totals.tokens_in ?? 0) + (totals.tokens_out ?? 0) : 0;
        cachedUsage = {
          plan: null,
          aiUsage: { used: tokens, limit: null },
          conversations: { used: null, limit: null },
          team: { used: null, limit: null },
          spend: totals ? Number(totals.cost ?? 0) : null,
        };
        setUsage(cachedUsage);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return usage ?? { plan: null, aiUsage: { used: 0, limit: null }, conversations: { used: null, limit: null }, team: { used: null, limit: null }, spend: null };
}

export function useRealChannels() {
  const [channels, setChannels] = useState(cachedChannels);
  useEffect(() => {
    if (cachedChannels) return;
    let alive = true;
    api("/integrations")
      .then((rows) => {
        if (!alive) return;
        cachedChannels = (Array.isArray(rows) ? rows : []).map((r) => ({
          id: r.provider,
          label: r.provider,
          connected: (r.status || "") === "connected",
        }));
        setChannels(cachedChannels);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return channels ?? [];
}
