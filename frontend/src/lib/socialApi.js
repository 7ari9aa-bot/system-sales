// Instagram posts and comments from the backend, shaped for InstagramPostsWorkspace.
import { api } from "@/lib/api";

const rel = (iso, lang) => {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  const ar = lang === "ar";
  if (mins < 1) return ar ? "الآن" : "Just now";
  if (mins < 60) return ar ? `منذ ${mins} د` : `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return ar ? `منذ ${hours} س` : `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 7) return ar ? `منذ ${days} ي` : `${days}d`;
  return new Date(iso).toLocaleDateString(ar ? "ar-EG" : "en-GB", { day: "numeric", month: "short" });
};

// A reply nests under its parent. Instagram threads are one level deep, so a flat list with
// parent ids is enough; anything whose parent is missing is shown at the top level.
export function toWorkspaceComments(items, lang = "ar", accountName = "") {
  const visible = (items || []).filter((c) => c.status !== "removed");
  const byId = new Map(
    visible.map((c) => [
      c.id,
      {
        id: c.id,
        author: c.is_page_reply ? accountName || "page" : c.username || "",
        handle: c.is_page_reply ? accountName || "page" : c.username || "",
        avatarUrl: "",
        timeLabel: rel(c.commented_at, lang),
        text: c.body || "",
        likes: c.like_count || 0,
        isPage: !!c.is_page_reply,
        isAgent: false,
        hidden: c.status === "hidden",
        repliedAt: c.replied_at,
        privateRepliedAt: c.private_replied_at,
        commentedAt: c.commented_at,
        replies: [],
      },
    ]),
  );
  const top = [];
  for (const c of visible) {
    const node = byId.get(c.id);
    const parent = c.parent_id ? byId.get(c.parent_id) : null;
    if (parent) parent.replies.push(node);
    else top.push(node);
  }
  return top;
}

export function toWorkspacePost(p, comments, lang = "ar", accountName = "") {
  return {
    id: p.id,
    accountName,
    accountAvatarUrl: "",
    timeLabel: rel(p.posted_at, lang),
    text: p.caption || "",
    mediaUrl: p.media_url || p.thumbnail_url || "",
    mediaType: /VIDEO|REELS/i.test(p.media_type || "") ? "video" : "image",
    isReel: /REELS/i.test(p.media_type || ""),
    likes: p.like_count || 0,
    commentsCount: p.comments_count || 0,
    commentsEnabled: p.comments_enabled !== false,
    permalink: p.permalink || "",
    comments: comments || [],
  };
}

export async function fetchPosts({ refresh = false, limit = 25 } = {}) {
  const q = new URLSearchParams({ limit: String(limit) });
  if (refresh) q.set("refresh", "true");
  return (await api(`/social/posts?${q}`)).items || [];
}

export async function fetchComments(postId, { refresh = false } = {}) {
  const q = refresh ? "?refresh=true" : "";
  return (await api(`/social/posts/${encodeURIComponent(postId)}/comments${q}`)).items || [];
}

const enc = encodeURIComponent;
export const replyToComment = (commentId, text) =>
  api(`/social/comments/${enc(commentId)}/reply`, { method: "POST", body: { text } });
export const setCommentHidden = (commentId, hidden) =>
  api(`/social/comments/${enc(commentId)}/hide`, { method: "POST", body: { hidden } });
export const deleteComment = (commentId) =>
  api(`/social/comments/${enc(commentId)}`, { method: "DELETE" });
export const privateReply = (commentId, text) =>
  api(`/social/comments/${enc(commentId)}/private-reply`, { method: "POST", body: { text } });
export const setPostCommentsEnabled = (postId, enabled) =>
  api(`/social/posts/${enc(postId)}/comments-enabled`, { method: "POST", body: { enabled } });
