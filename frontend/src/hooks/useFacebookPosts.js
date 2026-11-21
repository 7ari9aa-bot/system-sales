import { useCallback, useEffect, useRef, useState } from "react";
import {
  commentOn,
  deleteFacebookComment,
  deleteFacebookPost,
  editFacebookPost,
  fetchFacebookComments,
  fetchFacebookPosts,
  hideFacebookComment,
  likeObject,
  privateReplyFacebook,
  publishFacebookPost,
  toFacebookComments,
  toFacebookPost,
} from "@/lib/facebookApi";
import { browserWorld, startQuietRefresh } from "@/lib/quietRefresh";

// How often an open screen looks again at what the webhook stored. Our own copy, not Meta: cheap.
export const QUIET_REFRESH_MS = 45 * 1000;

// The Page's real posts and comments. Every action waits for Facebook, and a failure is thrown
// to the caller so the screen can say so, instead of pretending it was sent.
export function useFacebookPosts({ enabled, lang, pageName = "" }) {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true);
  // Bumped by every action the owner takes. A quiet look that started before one is stale: its answer
  // would put back the comment they just hid or answered, so it is dropped.
  const actionSeq = useRef(0);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async ({ refresh = false, quiet = false } = {}) => {
    if (!enabled) return;
    // A quiet look never shows the loading state or an error: the screen keeps what it has.
    if (!quiet) { setLoading(true); setError(""); }
    const startedAt = actionSeq.current;
    try {
      const raw = await fetchFacebookPosts({ refresh });
      const withComments = await Promise.all(
        raw.map(async (p) => {
          let items = [];
          try { items = await fetchFacebookComments(p.id, { refresh }); } catch { /* a post still shows without its comments */ }
          return toFacebookPost(p, toFacebookComments(items, lang, pageName), lang);
        }),
      );
      if (alive.current && !(quiet && startedAt !== actionSeq.current)) setPosts(withComments);
    } catch (e) {
      if (quiet) throw e; // the scheduler drops it; the screen is left as it was
      if (alive.current) setError(e?.message || "load failed");
    } finally {
      if (!quiet && alive.current) setLoading(false);
    }
  }, [enabled, lang, pageName]);

  useEffect(() => { load(); }, [load]);

  // A comment that arrives while the screen is open shows up here and in the notification count.
  useEffect(() => {
    if (!enabled) return undefined;
    return startQuietRefresh({ look: () => load({ quiet: true }), everyMs: QUIET_REFRESH_MS, ...browserWorld() });
  }, [enabled, load]);

  const reloadPost = useCallback(async (postId) => {
    actionSeq.current += 1;
    const items = await fetchFacebookComments(postId, { refresh: true });
    setPosts((prev) => prev.map((p) => (p.id === postId
      ? { ...p, comments: toFacebookComments(items, lang, pageName), commentsCount: items.filter((c) => c.status !== "removed").length }
      : p)));
  }, [lang, pageName]);

  return {
    posts,
    loading,
    error,
    refresh: () => load({ refresh: true }),
    comment: async (postId, text) => { await commentOn(postId, text); await reloadPost(postId); },
    reply: async (commentId, postId, text, mention) => { await commentOn(commentId, text, mention); await reloadPost(postId); },
    hide: async (commentId, postId, hidden) => { await hideFacebookComment(commentId, hidden); await reloadPost(postId); },
    removeComment: async (commentId, postId) => { await deleteFacebookComment(commentId); await reloadPost(postId); },
    sendPrivate: async (commentId, postId, text) => { await privateReplyFacebook(commentId, text); await reloadPost(postId); },
    like: (objectId, liked) => likeObject(objectId, liked),
    publish: async (input) => { const out = await publishFacebookPost(input); if (!input.scheduleAt) await load({ refresh: true }); return out; },
    edit: async (postId, message) => {
      actionSeq.current += 1;
      await editFacebookPost(postId, message);
      setPosts((prev) => prev.map((p) => (p.id === postId ? { ...p, text: message.trim() } : p)));
    },
    removePost: async (postId) => { actionSeq.current += 1; await deleteFacebookPost(postId); setPosts((prev) => prev.filter((p) => p.id !== postId)); },
  };
}
