import { useCallback, useEffect, useRef, useState } from "react";
import { apiCached, peekCache } from "@/lib/api";
import { CHANNELS } from "@/lib/channels";

/** بيانات استخدام حقيقية من الـbackend:
 *  - USAGE: استهلاك الذكاء من /ai/usage/summary. الـbackend مش بينشر
 *    «خطة» ولا «حدود باقة» ولا عدد المحادثات المسموحة — فالقيم دي
 *    بترجع null والشاشات بتخفيها بدل ما تعرض حدود وهمية.
 *  - CHANNELS: حالة القنوات الحقيقية من /integrations. */

export function useRealUsage() {
  const [usage, setUsage] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((current) => current + 1), []);

  useEffect(() => {
    let alive = true;
    apiCached("/ai/usage/summary", { ttlMs: 0 })
      .then((d) => {
        if (!alive) return;
        setUsage(d);
        setError("");
      })
      .catch((loadError) => {
        if (alive) setError(loadError?.message || "Could not load AI usage.");
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  return { data: usage, loading: usage == null && !error, error, retry };
}

export function useRealChannels() {
  const [state, setState] = useState({ channels: null, loading: true, error: "" });
  const requestId = useRef(0);
  const mounted = useRef(false);

  const mapIntegrations = useCallback((rows) => {
    const integrations = new Map((Array.isArray(rows) ? rows : []).map((row) => [row.provider, row]));
    return CHANNELS.map((channel) => {
      const integration = integrations.get(channel.id);
      const status = integration?.status || "not_connected";
      return {
        ...channel,
        integrationId: integration?.id ?? null,
        publicKey: integration?.public_key ?? null,
        status,
        connected: status === "connected" || status === "active",
      };
    });
  }, []);

  const reload = useCallback(async () => {
    const currentRequestId = ++requestId.current;
    setState((current) => ({ ...current, loading: current.channels == null, error: "" }));
    try {
      const rows = await apiCached("/integrations", { ttlMs: 0 });
      const mappedChannels = mapIntegrations(rows);
      if (mounted.current && currentRequestId === requestId.current) {
        setState({ channels: mappedChannels, loading: false, error: "" });
      }
      return mappedChannels;
    } catch (error) {
      if (mounted.current && currentRequestId === requestId.current) {
        setState((current) => ({
          ...current,
          loading: false,
          error: error?.message || "Could not load channel connections",
        }));
      }
      throw error;
    }
  }, [mapIntegrations]);

  useEffect(() => {
    mounted.current = true;
    const cached = peekCache("/integrations");
    if (Array.isArray(cached)) {
      setState({ channels: mapIntegrations(cached), loading: false, error: "" });
    }
    void reload().catch(() => {});
    return () => {
      mounted.current = false;
      requestId.current += 1;
    };
  }, [mapIntegrations, reload]);
  return { ...state, channels: state.channels ?? [], reload };
}
