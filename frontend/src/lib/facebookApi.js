// The Facebook Page's posts and comments from the backend, shaped for the Facebook pages.
// Limits are Meta's own (Pages API: Posts): a scheduled post goes live 10 minutes to 30 days
// from now, and a post carries a link or a picture, not both.
import { api } from "@/lib/api";

const enc = encodeURIComponent;

export const FB_LIMITS = {
  maxPostChars: 63206,
  scheduleMinMinutes: 10,
  scheduleMaxDays: 30,
  maxCommentChars: 8000,
};

/** Short Facebook-style age: "Just now", "5m", "3h", "2d", then the date. */
export function fbAge(iso, lang = "ar") {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const ar = lang === "ar";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return ar ? "الآن" : "Just now";
  if (mins < 60) return ar ? `${mins} د` : `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return ar ? `${hours} س` : `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 7) return ar ? `${days} ي` : `${days}d`;
  return new Date(iso).toLocaleDateString(ar ? "ar-EG" : "en-GB", { day: "numeric", month: "short", year: days > 330 ? "numeric" : undefined });
}

/** Comments arrive flat with parent ids; a reply nests under its parent (Facebook threads are one level deep). */
export function toFacebookComments(items, lang = "ar", pageName = "") {
  const visible = (items || []).filter((c) => c.status !== "removed");
  const byId = new Map(
    visible.map((c) => [
      c.id,
      {
        id: c.id,
        author: c.is_page_reply ? pageName || "page" : c.username || "",
        timeLabel: fbAge(c.commented_at, lang),
        commentedAt: c.commented_at,
        text: c.body || "",
        likes: c.like_count || 0,
        isPage: !!c.is_page_reply,
        hidden: c.status === "hidden",
        repliedAt: c.replied_at,
        privateRepliedAt: c.private_replied_at,
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

export function toFacebookPost(p, comments, lang = "ar") {
  return {
    id: p.id,
    text: p.message || "",
    picture: p.picture || "",
    type: p.type || "STATUS",
    permalink: p.permalink || "",
    reactions: p.reactions || 0,
    commentsCount: p.comments || 0,
    postedAt: p.posted_at,
    timeLabel: fbAge(p.posted_at, lang),
    comments: comments || [],
  };
}

export const fetchPage = () => api("/facebook/page");

export async function fetchFacebookPosts({ refresh = false, limit = 25 } = {}) {
  const q = new URLSearchParams({ limit: String(limit) });
  if (refresh) q.set("refresh", "true");
  return (await api(`/facebook/posts?${q}`)).items || [];
}

export async function fetchScheduled() {
  return (await api("/facebook/scheduled")).items || [];
}

export async function fetchFacebookComments(postId, { refresh = false } = {}) {
  const q = refresh ? "?refresh=true" : "";
  return (await api(`/facebook/posts/${enc(postId)}/comments${q}`)).items || [];
}

export const publishFacebookPost = ({ message, link, scheduleAt }) =>
  api("/facebook/posts", {
    method: "POST",
    body: {
      message: (message || "").trim() || null,
      link: (link || "").trim() || null,
      schedule_at: scheduleAt ? new Date(scheduleAt).toISOString() : null,
    },
  });

export const editFacebookPost = (postId, message) =>
  api(`/facebook/posts/${enc(postId)}`, { method: "PATCH", body: { message } });
export const deleteFacebookPost = (postId) => api(`/facebook/posts/${enc(postId)}`, { method: "DELETE" });

/** A comment on a post, or a reply when `objectId` is a comment. */
export const commentOn = (objectId, text) =>
  api(`/facebook/objects/${enc(objectId)}/comments`, { method: "POST", body: { text } });
export const likeObject = (objectId, liked) =>
  api(`/facebook/objects/${enc(objectId)}/like`, { method: "POST", body: { liked } });
export const hideFacebookComment = (commentId, hidden) =>
  api(`/facebook/comments/${enc(commentId)}/hide`, { method: "POST", body: { hidden } });
export const deleteFacebookComment = (commentId) => api(`/facebook/comments/${enc(commentId)}`, { method: "DELETE" });
export const privateReplyFacebook = (commentId, text) =>
  api(`/facebook/comments/${enc(commentId)}/private-reply`, { method: "POST", body: { text } });

export async function fetchFacebookPostInsights(postId) {
  return (await api(`/facebook/posts/${enc(postId)}/insights`))?.metrics || [];
}
export async function fetchFacebookInsights() {
  return (await api("/facebook/insights"))?.metrics || [];
}

/** Why this post cannot be sent, or "" when it can. Checked before anything leaves the browser. */
export function facebookPostProblem({ message = "", link = "", scheduleAt = "" }, lang = "ar", now = Date.now()) {
  const ar = lang === "ar";
  const text = message.trim();
  const url = link.trim();
  if (!text && !url) return ar ? "اكتب نصًا أو أضف رابطًا" : "Write something or add a link";
  if (text.length > FB_LIMITS.maxPostChars) return ar ? "المنشور أطول من الحد المسموح" : "The post is longer than Facebook allows";
  if (url && !/^https?:\/\/\S+$/i.test(url)) return ar ? "الرابط يجب أن يبدأ بـ http أو https" : "The link must start with http or https";
  if (scheduleAt) {
    const at = new Date(scheduleAt).getTime();
    if (!Number.isFinite(at)) return ar ? "موعد النشر غير صالح" : "The schedule time is not valid";
    const mins = (at - now) / 60000;
    if (mins < FB_LIMITS.scheduleMinMinutes) return ar ? "الجدولة بعد 10 دقائق على الأقل من الآن" : "Schedule at least 10 minutes from now";
    if (mins > FB_LIMITS.scheduleMaxDays * 1440) return ar ? "الجدولة خلال 30 يومًا كحد أقصى" : "Schedule within 30 days at most";
  }
  return "";
}
