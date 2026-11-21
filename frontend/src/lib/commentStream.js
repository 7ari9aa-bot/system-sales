/**
 * Opens the realtime stream for comments.
 *
 * A browser stream cannot send headers, so it carries a short-lived, stream-only token in the
 * address. That token lasts five minutes, so a FRESH one is fetched before every open: a stream
 * that drops and reconnects an hour later must not present the old one. The token, the stream
 * class and the base path are passed in, so this is tested with no browser.
 */
import { api, apiUrl } from "@/lib/api";

export function streamUrl(base, token) {
  return `${base}/realtime/events?streams=social_comment.events&token=${encodeURIComponent(token)}`;
}

/**
 * @returns open() => { ready, close(), onopen, onmessage, onerror }
 *   the same shape the push listener uses, whether or not the real stream exists yet.
 */
export function createCommentStream({ mint, Source, base }) {
  return function open() {
    let real = null;
    let closed = false;
    const handle = {
      onopen: null,
      onmessage: null,
      onerror: null,
      close() {
        closed = true;
        if (real) real.close();
      },
    };
    handle.ready = (async () => {
      let token;
      try {
        ({ stream_token: token } = await mint());
      } catch {
        if (!closed) handle.onerror?.();
        return;
      }
      if (closed) return;
      real = new Source(streamUrl(base, token));
      real.onopen = (e) => handle.onopen?.(e);
      real.onmessage = (e) => handle.onmessage?.(e);
      real.onerror = (e) => handle.onerror?.(e);
    })();
    return handle;
  };
}

/** The browser's own stream, minting its token through the signed-in session. */
export function openCommentStream() {
  return createCommentStream({
    mint: () => api("/realtime/stream-token", { method: "POST" }),
    Source: EventSource,
    base: apiUrl("/").replace(/\/$/, ""),
  })();
}
