import { useEffect, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";
import { CHANNELS } from "@/lib/channels";

/** بيانات استخدام حقيقية من الـbackend:
 *  - USAGE: استهلاك الذكاء من /ai/usage/summary. الـbackend مش بينشر
 *    «خطة» ولا «حدود باقة» ولا عدد المحادثات المسموحة — فالقيم دي
 *    بترجع null والشاشات بتخفيها بدل ما تعرض حدود وهمية.
 *  - CHANNELS: حالة القنوات الحقيقية من /integrations. */

export function useRealUsage() {
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    let alive = true;
    apiCached("/ai/usage/summary")
      .then((d) => {
        if (!alive) return;
        const totals = d?.totals ?? null;
        const tokens = totals ? (totals.tokens_in ?? 0) + (totals.tokens_out ?? 0) : 0;
        setUsage({
          plan: null,
          aiUsage: { used: tokens, limit: null },
          conversations: { used: null, limit: null },
          team: { used: null, limit: null },
          spend: totals ? Number(totals.cost ?? 0) : null,
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return usage ?? { plan: null, aiUsage: { used: 0, limit: null }, conversations: { used: null, limit: null }, team: { used: null, limit: null }, spend: null };
}

export function useRealChannels() {
  const [state, setState] = useState({ channels: null, loading: true, error: "" });
  useEffect(() => {
    let alive = true;
    const cached = peekCache("/integrations");
    if (Array.isArray(cached)) {
      const connected = new Map(cached.map((row) => [row.provider, row]));
      const rows = CHANNELS.map((channel) => {
        const integration = connected.get(channel.id);
        const status = integration?.status || "not_connected";
        return { ...channel, status, connected: status === "connected" || status === "active" };
      });
      setState({ channels: rows, loading: false, error: "" });
    }
    apiCached("/integrations", { ttlMs: 15_000 })
      .then((rows) => {
        if (!alive) return;
        const integrations = new Map((Array.isArray(rows) ? rows : []).map((row) => [row.provider, row]));
        const mappedChannels = CHANNELS.map((channel) => {
          const integration = integrations.get(channel.id);
          const status = integration?.status || "not_connected";
          return { ...channel, status, connected: status === "connected" || status === "active" };
        });
        setState({ channels: mappedChannels, loading: false, error: "" });
      })
      .catch((error) => {
        if (alive) setState((current) => ({
          ...current,
          loading: false,
          error: error?.message || "Could not load channel connections",
        }));
      });
    return () => {
      alive = false;
    };
  }, []);
  return { ...state, channels: state.channels ?? [] };
}
