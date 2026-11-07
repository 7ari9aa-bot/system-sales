/** Sends what the guardian already collects to the owner console.
 *
 *  The guardian (lib/guardian.js) catches API, window, promise and render failures, but it
 *  only keeps them in memory and shows a badge in DEV, so in production every real failure was
 *  lost. This subscribes to it and forwards each NEW failure to /public/telemetry as an
 *  `error` event, which the owner console lists on its Errors page.
 *
 *  Hard limits, because telemetry must never hurt the page that emits it:
 *   - at most MAX_PER_SESSION events and one per MIN_GAP_MS (a render loop cannot flood the API);
 *   - a repeated failure (the guardian bumps `count`) is not re-sent;
 *   - the message is cut, and the path is the route only, never a query string (tokens live there);
 *   - it uses fetch directly, never api(), so a failing telemetry call cannot report itself. */

import { guardianSubscribe } from "./guardian";
import { apiUrl } from "./api";
import { VISITOR_KEY, SESSION_KEY, getOrCreate } from "./visitorId";

export const MAX_PER_SESSION = 20;
export const MIN_GAP_MS = 1000;
const MAX_MESSAGE = 300;

/** HTTP status out of a guardian message such as "HTTP 503"; null when there is none. */
export function statusFromMessage(message) {
  const m = /\bHTTP (\d{3})\b/.exec(String(message || ""));
  if (!m) return null;
  const n = Number(m[1]);
  return n >= 100 && n <= 599 ? n : null;
}

/** Pure: should this guardian event be forwarded? Kept free of I/O so it can be unit-tested.
 *  `state.seen` holds ids already handled: the guardian merges a repeat into an OLDER entry
 *  (bumping its count), so "the last element" is not a reliable sign that something is new. */
export function shouldForward(event, state, now) {
  if (!event || state.seen.has(event.id)) return false;
  if ((event.count ?? 1) > 1) return false;
  if (state.sent >= MAX_PER_SESSION) return false;
  if (now - state.lastAt < MIN_GAP_MS) return false;
  return true;
}

export function toTelemetryEvent(
  event,
  { visitorId, sessionId, path, origin },
) {
  const status = event.status || statusFromMessage(event.message);
  return {
    visitor_id: visitorId,
    session_id: sessionId,
    event_type: "error",
    path,
    url: `${origin}${path}`,
    element: String(event.message || "error").slice(0, MAX_MESSAGE),
    ...(status ? { status_code: status } : {}),
    metadata: {
      kind: event.kind,
      source: String(event.source || "").slice(0, 120),
    },
  };
}

let started = false;
const state = { sent: 0, lastAt: 0, seen: new Set() };

export function startErrorTelemetry() {
  if (started || typeof window === "undefined") return;
  started = true;
  guardianSubscribe((events) => {
    const now = Date.now();
    // Every entry the guardian holds that we have not handled yet (normally just the newest).
    for (const event of events) {
      if (state.seen.has(event.id)) continue;
      const forward = shouldForward(event, state, now);
      state.seen.add(event.id); // handled either way: a throttled event is dropped, not retried
      if (!forward) continue;
      state.sent += 1;
      state.lastAt = now;
      send(event);
    }
  });
}

function send(event) {
  try {
    const payload = toTelemetryEvent(event, {
      visitorId: getOrCreate(localStorage, VISITOR_KEY),
      sessionId: getOrCreate(sessionStorage, SESSION_KEY),
      path: window.location.pathname, // pathname only: no query string
      origin: window.location.origin,
    });
    fetch(apiUrl("/public/telemetry"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: "omit",
    }).catch(() => {});
  } catch {
    // Telemetry must never break the page.
  }
}

/** Test seam: forget the per-session counters. */
export function _resetErrorTelemetryForTests() {
  started = false;
  state.sent = 0;
  state.lastAt = 0;
  state.seen = new Set();
}
