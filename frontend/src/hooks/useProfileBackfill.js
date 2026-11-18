import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

const PARALLEL = 2; // a gentle trickle: this is a courtesy, never a burst against the platform
const MAX_PER_PASS = 12;

// Instagram names a customer only by a number until their profile is read. For chats on screen that
// still lack a name or photo, ask the backend once per chat per visit (it also rate-limits itself:
// a week after a success, six hours after a refusal), then reload the list a single time.
export function useProfileBackfill({ rows, enabled, reload }) {
  const tried = useRef(new Set());
  const running = useRef(false);

  useEffect(() => {
    if (!enabled || running.current) return;
    const todo = (rows || []).filter((r) => r.channel === "instagram" && r.needsProfile && !tried.current.has(r.id)).slice(0, MAX_PER_PASS);
    if (!todo.length) return;
    running.current = true;
    todo.forEach((r) => tried.current.add(r.id));
    let cancelled = false;
    (async () => {
      let learned = false;
      for (let i = 0; i < todo.length && !cancelled; i += PARALLEL) {
        const results = await Promise.allSettled(
          todo.slice(i, i + PARALLEL).map((r) => api(`/conversations/${encodeURIComponent(r.id)}/refresh-profile`, { method: "POST", retry: false })),
        );
        if (results.some((x) => x.status === "fulfilled" && x.value?.updated)) learned = true;
      }
      running.current = false;
      if (learned && !cancelled) await reload?.();
    })();
    return () => { cancelled = true; running.current = false; };
  }, [rows, enabled, reload]);
}
