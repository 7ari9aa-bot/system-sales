import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteComment,
  fetchComments,
  fetchPosts,
  privateReply,
  publishPost,
  replyToComment,
  setCommentHidden,
  setPostCommentsEnabled,
  toWorkspaceComments,
  toWorkspacePost,
} from "@/lib/socialApi";

// The store's real Instagram posts and comments. Every action waits for the platform,
// and a failure is thrown to the caller so the screen can say so, instead of pretending it was sent.
export function useInstagramPosts({ enabled, lang, accountName = "" }) {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async ({ refresh = false } = {}) => {
    if (!enabled) return;
    setLoading(true);
    setError("");
    try {
      const raw = await fetchPosts({ refresh });
      const withComments = await Promise.all(
        raw.map(async (p) => {
          let items = [];
          try { items = await fetchComments(p.id, { refresh }); } catch { /* a post still shows without its comments */ }
          return toWorkspacePost(p, toWorkspaceComments(items, lang, accountName), lang, accountName);
        }),
      );
      if (alive.current) setPosts(withComments);
    } catch (e) {
      if (alive.current) setError(e?.message || "load failed");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [enabled, lang, accountName]);

  useEffect(() => { load(); }, [load]);

  const reloadPost = useCallback(async (postId) => {
    const items = await fetchComments(postId);
    setPosts((prev) => prev.map((p) => (p.id === postId ? { ...p, comments: toWorkspaceComments(items, lang, accountName) } : p)));
  }, [lang, accountName]);

  return {
    posts,
    loading,
    error,
    refresh: () => load({ refresh: true }),
    reply: async (commentId, postId, text) => { await replyToComment(commentId, text); await reloadPost(postId); },
    hide: async (commentId, postId, hidden) => { await setCommentHidden(commentId, hidden); await reloadPost(postId); },
    remove: async (commentId, postId) => { await deleteComment(commentId); await reloadPost(postId); },
    sendPrivate: async (commentId, postId, text) => { await privateReply(commentId, text); await reloadPost(postId); },
    publish: async (files, caption) => { const out = await publishPost(files, caption); await load({ refresh: true }); return out; },
    toggleComments: async (postId, on) => {
      await setPostCommentsEnabled(postId, on);
      setPosts((prev) => prev.map((p) => (p.id === postId ? { ...p, commentsEnabled: on } : p)));
    },
  };
}
