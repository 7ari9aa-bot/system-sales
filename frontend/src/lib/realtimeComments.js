/**
 * Tells an open Facebook screen that a comment was stored, the moment the server stores it.
 *
 * The server announces `social_comment.changed` (ids only, never the text) on the realtime stream
 * after the webhook writes the comment. This listens for it and reloads just that post through the
 * screen's ordinary authenticated read. The timer, the stream and the reload are passed in, so it is
 * tested with no browser. It only ever ADDS speed: the slow look every 45 seconds stays, so a dropped
 * stream costs a little delay and never a missing comment.
 */

const COMMENT_STREAM = "social_comment.events";
// A comment and its first reply often land together; wait this long so they cost one reload.
export const SETTLE_MS = 150;
const BASE_MS = 1000;
const MAX_MS = 30000;

/** The post a frame is about, or null when it is not a Facebook comment frame. Never throws. */
export function postIdOfFrame(data) {
  try {
    const frame = JSON.parse(data);
    if (!frame || frame.stream !== COMMENT_STREAM) return null;
    const p = frame.payload || {};
    if (p.platform !== "facebook") return null;
    return typeof p.post_id === "string" && p.post_id ? p.post_id : null;
  } catch {
    return null;
  }
}

/** 1s, 2s, 4s ... capped at 30s, so a server that is down is not hammered. */
export function backoffMs(attempt) {
  return Math.min(MAX_MS, BASE_MS * 2 ** Math.max(0, attempt));
}

/**
 * @param reload (postId) => Promise  reloads one post's comments from our own copy
 * @param open   () => stream          opens the stream; `.close()`, `.onmessage`, `.onerror`, `.onopen`
 * Returns stop().
 */
export function startCommentPush({ reload, open, setTimer, clearTimer }) {
  let stopped = false;
  let source = null;
  let attempt = 0;
  let retry = null;
  const pending = new Map(); // postId -> settle timer

  function wake(postId) {
    if (stopped || pending.has(postId)) return; // already queued: this comment rides along
    const t = setTimer(async () => {
      pending.delete(postId);
      if (stopped) return;
      try { await reload(postId); } catch { /* the next look picks it up */ }
    }, SETTLE_MS);
    pending.set(postId, t);
  }

  function connect() {
    if (stopped) return;
    source = open();
    source.onopen = () => { attempt = 0; };
    source.onmessage = (event) => {
      const postId = postIdOfFrame(event?.data);
      if (postId) wake(postId);
    };
    source.onerror = () => {
      if (stopped) return;
      source.close();
      source = null;
      retry = setTimer(() => { retry = null; connect(); }, backoffMs(attempt));
      attempt += 1;
    };
  }

  connect();

  return function stop() {
    stopped = true;
    if (retry) clearTimer(retry);
    pending.forEach((t) => clearTimer(t));
    pending.clear();
    if (source) source.close();
  };
}
