import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

/** اشتراك SSE في أحداث المجال — عين التيلات المفتوحة.
 *
 * التوكن بتاع الـ EventSource بيخلص بعد 5 دقايق (SEC-1)، فأي قطع بنقفل
 * وبنعيد النداء بتوكن جديد بعد مهلة — مفيش reconnect عشوائي بتوكن ميت. */
export default function useRealtime(streams, onEvent, enabled = true) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const streamsKey = (streams || []).join(",");

  useEffect(() => {
    if (!enabled) return undefined;
    let disposed = false;
    let source = null;
    let timer = null;

    async function connect() {
      if (disposed) return;
      try {
        const { stream_token: token } = await api("/realtime/stream-token", {
          method: "POST",
        });
        if (disposed) return;
        const params = new URLSearchParams({ token });
        for (const s of streamsKey ? streamsKey.split(",") : []) {
          params.append("streams", s);
        }
        source = new EventSource(`/api/v1/realtime/events?${params.toString()}`);
        source.onmessage = (e) => {
          try {
            handlerRef.current?.(JSON.parse(e.data));
          } catch {
            /* إطار تالف — نتجاهله والاتصال مكمل */
          }
        };
        source.onerror = () => {
          source?.close();
          source = null;
          if (!disposed) timer = setTimeout(connect, 5000);
        };
      } catch {
        if (!disposed) timer = setTimeout(connect, 10000);
      }
    }

    void connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [enabled, streamsKey]);
}
