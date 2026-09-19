/**
 * useRealtimeEvents — SSE client for the /api/v1/realtime/events endpoint.
 *
 * Connects once on mount, reconnects automatically with exponential backoff,
 * and passes every event to the supplied `onEvent` callback.
 * The cursor (last received event ID) is preserved across reconnects so no
 * events are missed during transient disconnects (subject to Redis retention).
 *
 * Usage:
 *   useRealtimeEvents({
 *     streams: ["message.events", "conversation.events"],
 *     onEvent: (stream, payload) => { ... },
 *   });
 */

import { useEffect, useRef, useCallback } from "react";
import { getTokens } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SSE_URL = `${API}/api/v1/realtime/events`;

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

export function useRealtimeEvents({
  streams,
  onEvent,
  enabled = true,
}: UseRealtimeEventsOptions): void {
  const cursorRef = useRef<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const attemptsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent; // always latest without re-connecting

  const connect = useCallback(() => {
    const tokens = getTokens();
    if (!tokens?.access_token) return;

    // Build URL with query params.
    const url = new URL(SSE_URL);
    if (streams?.length) {
      for (const s of streams) url.searchParams.append("streams", s);
    }
    if (cursorRef.current) {
      url.searchParams.set("cursor", cursorRef.current);
    }
    // SSE doesn't support custom headers — we pass the token as a query param
    // for the initial handshake.  The backend reads it from `?token=`.
    // NOTE: If the backend requires Bearer header-only auth, use a short-lived
    // token exchange endpoint instead (not yet implemented).
    url.searchParams.set("token", tokens.access_token);

    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const es = new EventSource(url.toString());
    esRef.current = es;

    es.onopen = () => {
      attemptsRef.current = 0; // reset backoff on successful open
    };

    es.onmessage = (e: MessageEvent<string>) => {
      try {
        const frame = JSON.parse(e.data) as RealtimeEvent;
        // Update cursor for reconnect.
        if (frame.id) cursorRef.current = frame.id;
        onEventRef.current(frame);
      } catch {
        // Malformed frame — ignore.
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;

      if (!enabled) return;

      // Exponential backoff.
      const delay = Math.min(
        BACKOFF_BASE_MS * Math.pow(BACKOFF_MULTIPLIER, attemptsRef.current),
        BACKOFF_MAX_MS
      );
      attemptsRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };
  }, [streams, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!enabled) {
      esRef.current?.close();
      esRef.current = null;
      return;
    }
    connect();

    return () => {
      esRef.current?.close();
      esRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [connect, enabled]);
}
