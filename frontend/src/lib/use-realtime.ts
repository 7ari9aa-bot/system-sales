/**
 * useRealtimeEvents — SSE client for the /api/v1/realtime/events endpoint.
 *
 * Connects once on mount, reconnects automatically with exponential backoff,
 * and passes every event to the supplied `onEvent` callback.
 * The cursor (last received event ID) is preserved across reconnects so no
 * events are missed during transient disconnects (subject to Redis retention).
 *
 * Why this does NOT use `EventSource` (review G-07):
 *
 * `EventSource` cannot set request headers, so the access token had to be
 * passed as `?token=` — which puts a live credential into server access logs,
 * browser history, and any `Referer` sent from that URL. The backend has always
 * accepted `Authorization: Bearer` on this route (`_sse_auth` tries the header
 * first and only falls back to `?token=`), so the URL token was avoidable.
 *
 * A `fetch` + `ReadableStream` reader sends the header normally and keeps the
 * token out of every URL. It also makes the stream abortable, which the
 * previous implementation could only approximate with `es.close()`.
 *
 * Usage:
 *   useRealtimeEvents({
 *     streams: ["message.events", "conversation.events"],
 *     onEvent: (stream, payload) => { ... },
 *   });
 */

import { useEffect, useRef, useCallback } from "react";
import { absoluteApiUrl, getTokens } from "@/lib/api";

/** The stream route, resolved by the ONE url rule in the app.
 *
 *  This used to read `NEXT_PUBLIC_API_URL` itself with a `http://localhost:8000`
 *  fallback — a third copy of the base rule, and the only one whose default was
 *  an absolute origin. Deployed without the variable set (which is how the
 *  same-origin Vercel rewrite is meant to work), every browser then opened its
 *  event stream against the developer's machine: realtime silently dead in
 *  production while every REST call kept working through `/api/v1`.
 *
 *  Routing it through `apiUrl()` instead fixed that and broke something worse,
 *  because `apiUrl()` answers with a RELATIVE path under the default shape and
 *  the URL constructor rejects a relative argument outright. The old code could
 *  not crash — an absolute string always parses; the new one threw the moment
 *  `connect()` tried to build its URL, inside the bell's mount effect. That
 *  effect lives in `Shell`, which the dashboard layout wraps in `ErrorBoundary`,
 *  so the whole shell — nav, user menu, page — was replaced by "Something went
 *  wrong: Failed to construct 'URL': Invalid URL" on every authenticated
 *  screen, for every merchant, on the default deployment shape.
 *  It survived lint, `npm run build` and all four browserless checks, because
 *  every one of them stops before a dashboard component's effect runs, and the
 *  e2e job — the only thing that mounts the shell with a token in storage —
 *  reported it as a wall of `toBeVisible()` failures that never said "URL".
 *
 *  Hence: a PATH at module scope (safe to evaluate anywhere, including the
 *  server), and an absolute URL only at the moment of use. `sseUrl` is exported
 *  so `npm run check:urls` can prove both shapes browserlessly — that gate runs
 *  on every push and needs no port. */
const SSE_PATH = "/realtime/events";

/** The event-stream URL for the document that is asking, with the non-secret
 *  query state already applied. Exported for `scripts/check-request-urls.mjs`. */
export function sseUrl(
  origin: string,
  { streams, cursor }: { streams?: string[]; cursor?: string | null } = {},
): URL {
  const url = new URL(absoluteApiUrl(SSE_PATH, origin));
  if (streams?.length) {
    for (const s of streams) url.searchParams.append("streams", s);
  }
  if (cursor) url.searchParams.set("cursor", cursor);
  return url;
}

export interface RealtimeEvent {
  stream: string;
  id: string;
  payload: Record<string, unknown>;
}

interface UseRealtimeEventsOptions {
  /** Streams to subscribe to. Default: all. */
  streams?: string[];
  /** Called for every event received. Stable reference recommended (useCallback). */
  onEvent: (event: RealtimeEvent) => void;
  /** Disable the connection (e.g. when the user is not logged in). */
  enabled?: boolean;
}

const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const BACKOFF_MULTIPLIER = 2;

/** Parse one SSE frame. Returns null for comments/heartbeats and bad JSON. */
function parseFrame(raw: string): RealtimeEvent | null {
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    // SSE allows CRLF; the \r would otherwise end up inside the JSON.
    const clean = line.endsWith("\r") ? line.slice(0, -1) : line;
    // A leading ':' is a comment — the server's heartbeat.
    if (clean.startsWith("data:")) dataLines.push(clean.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  try {
    return JSON.parse(dataLines.join("\n")) as RealtimeEvent;
  } catch {
    // Malformed frame — ignore, exactly as the EventSource version did.
    return null;
  }
}

export function useRealtimeEvents({
  streams,
  onEvent,
  enabled = true,
}: UseRealtimeEventsOptions): void {
  const cursorRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const attemptsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent; // always latest without re-connecting

  const connect = useCallback(() => {
    const tokens = getTokens();
    if (!tokens?.access_token) return;

    // Resolved at connect time, not at module scope: it needs the origin of the
    // document that is opening the stream, and only non-secret state goes in it.
    const url = sseUrl(window.location.origin, { streams, cursor: cursorRef.current });

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const scheduleRetry = () => {
      if (controller.signal.aborted || !enabled) return;
      const delay = Math.min(
        BACKOFF_BASE_MS * Math.pow(BACKOFF_MULTIPLIER, attemptsRef.current),
        BACKOFF_MAX_MS,
      );
      attemptsRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    const handleFrame = (raw: string) => {
      const frame = parseFrame(raw);
      if (!frame) return;
      // Update the cursor so a reconnect resumes where this one stopped.
      if (frame.id) cursorRef.current = frame.id;
      onEventRef.current(frame);
    };

    void (async () => {
      try {
        const res = await fetch(url.toString(), {
          headers: {
            Authorization: `Bearer ${tokens.access_token}`,
            Accept: "text/event-stream",
          },
          signal: controller.signal,
          cache: "no-store",
        });

        if (!res.ok || !res.body) {
          scheduleRetry();
          return;
        }

        attemptsRef.current = 0; // reset backoff on a successful open

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // Frames are separated by a blank line.
          let separator = buffer.indexOf("\n\n");
          while (separator !== -1) {
            handleFrame(buffer.slice(0, separator));
            buffer = buffer.slice(separator + 2);
            separator = buffer.indexOf("\n\n");
          }
        }

        // The server closed the stream cleanly — reconnect from the cursor.
        scheduleRetry();
      } catch {
        // An abort is an unmount/disable, not a failure to retry.
        if (controller.signal.aborted) return;
        scheduleRetry();
      }
    })();
  }, [streams, enabled]);

  useEffect(() => {
    if (!enabled) {
      abortRef.current?.abort();
      abortRef.current = null;
      return;
    }
    connect();

    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [connect, enabled]);
}
