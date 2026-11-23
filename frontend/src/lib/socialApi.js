// Instagram posts and comments from the backend, shaped for the Instagram pages.
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
    isStory: /STORIES/i.test(p.media_type || ""),
    // Meta's numbers for a story, exactly as delivered: a missing key means "not sent yet", and
    // -1 means "fewer than five", which is not zero.
    insights: p.insights && typeof p.insights === "object" ? p.insights : {},
    likes: p.like_count || 0,
    commentsCount: p.comments_count || 0,
    commentsEnabled: p.comments_enabled !== false,
    permalink: p.permalink || "",
    comments: comments || [],
  };
}

/** Meta's "fewer than five" sentinel, named so no screen writes `=== -1` from memory. */
export const BELOW_THRESHOLD = -1;

/**
 * One story metric as the owner should read it.
 *
 * Three different situations, three different answers: Meta has not sent it yet (null), Meta sent
 * -1 because the real count is under five, or a real number.
 */
export function storyMetric(value, isAr) {
  if (value === null || value === undefined || value === "") {
    return { value: null, text: isAr ? "لسه موصلناش" : "Not delivered yet", belowThreshold: false };
  }
  if (value === BELOW_THRESHOLD) {
    return { value: null, text: isAr ? "أقل من ٥" : "Fewer than 5", belowThreshold: true };
  }
  return { value, text: String(value), belowThreshold: false };
}

/** The metrics worth showing on a story, in the order Instagram itself shows them. */
export const STORY_METRICS = [
  ["impressions", "مرات الظهور", "Impressions"],
  ["reach", "الوصول", "Reach"],
  ["replies", "الردود", "Replies"],
  ["taps_forward", "تخطّي", "Taps forward"],
  ["taps_back", "رجوع", "Taps back"],
  ["exits", "خروج", "Exits"],
];

/** A story's rows for the screen: only the metrics Meta actually named. */
export function storyRows(insights, isAr) {
  const source = insights && typeof insights === "object" ? insights : {};
  return STORY_METRICS.filter(([key]) => Object.prototype.hasOwnProperty.call(source, key)).map(
    ([key, ar, en]) => ({ key, label: isAr ? ar : en, ...storyMetric(source[key], isAr) }),
  );
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

// Publishing: Instagram takes JPEG only, 1 picture or 2-10 as a carousel, 8 MB each, caption up to 2,200.
export const PUBLISH_LIMITS = { maxPictures: 10, maxBytes: 8 * 1024 * 1024, maxCaption: 2200 };

/** Why these files cannot be published, or "" when they can. Checked before anything is uploaded. */
export function publishProblem(files, caption = "", lang = "ar") {
  const ar = lang === "ar";
  if (!files.length) return ar ? "أضف صورة واحدة على الأقل" : "Add at least one picture";
  if (files.length > PUBLISH_LIMITS.maxPictures) return ar ? "الحد الأقصى 10 صور في المنشور" : "A post holds at most 10 pictures";
  for (let i = 0; i < files.length; i += 1) {
    const f = files[i];
    if (!/^image\/jpe?g$/i.test(f.type || "")) return ar ? `الصورة ${i + 1} ليست JPEG. إنستغرام يقبل JPEG فقط` : `Picture ${i + 1} is not a JPEG. Instagram accepts JPEG only`;
    if (f.size > PUBLISH_LIMITS.maxBytes) return ar ? `الصورة ${i + 1} أكبر من 8 ميغابايت` : `Picture ${i + 1} is larger than 8 MB`;
  }
  if ((caption || "").length > PUBLISH_LIMITS.maxCaption) return ar ? "النص أطول من 2200 حرف" : "The caption is longer than 2,200 characters";
  return "";
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("could not read the picture"));
    reader.readAsDataURL(file);
  });
}

export async function publishPost(files, caption) {
  const pictures = await Promise.all(files.map(toBase64));
  return api("/social/posts", { method: "POST", body: { pictures, caption: (caption || "").trim() || null } });
}

export const REEL_LIMITS = { maxBytes: 100 * 1024 * 1024, maxCaption: 2200 };

/** Why this video cannot go out as a Reel, or "" when it can. Checked before uploading. */
export function reelProblem(file, caption = "", lang = "ar") {
  const ar = lang === "ar";
  if (!file) return ar ? "اختر فيديو للريل" : "Choose a video for the Reel";
  if (!/^video\/(mp4|quicktime)$/i.test(file.type || "")) return ar ? "الريل لازم يكون فيديو MP4 أو MOV. إنستغرام يقبل النوعين دول فقط" : "A Reel must be an MP4 or MOV video. Instagram accepts those only";
  if (file.size > REEL_LIMITS.maxBytes) return ar ? "الفيديو أكبر من 100 ميغابايت" : "The video is larger than 100 MB";
  if ((caption || "").length > REEL_LIMITS.maxCaption) return ar ? "النص أطول من 2200 حرف" : "The caption is longer than 2,200 characters";
  return "";
}

/** Why this file cannot go out as a story, or "" when it can. */
export function storyProblem(file, lang = "ar") {
  const ar = lang === "ar";
  if (!file) return ar ? "اختر صورة أو فيديو للستوري" : "Choose a picture or a video for the story";
  if (/^image\/jpe?g$/i.test(file.type || "")) return file.size > PUBLISH_LIMITS.maxBytes ? (ar ? "الصورة أكبر من 8 ميغابايت" : "The picture is larger than 8 MB") : "";
  if (/^video\/(mp4|quicktime)$/i.test(file.type || "")) return file.size > REEL_LIMITS.maxBytes ? (ar ? "الفيديو أكبر من 100 ميغابايت" : "The video is larger than 100 MB") : "";
  return ar ? "الستوري صورة JPEG أو فيديو MP4/MOV فقط" : "A story is a JPEG picture or an MP4/MOV video";
}

/** Publish a Reel. `shareToFeed` is the merchant's choice, not our default to hide. */
export async function publishReel(file, caption, { shareToFeed = true } = {}) {
  const video = await toBase64(file);
  return api("/social/reels", { method: "POST", body: { video, caption: (caption || "").trim() || null, share_to_feed: Boolean(shareToFeed) } });
}

/** Publish a story: a picture or a video, and no caption — Instagram has no field for one. */
export async function publishStory(file) {
  const media = await toBase64(file);
  const isVideo = /^video\//i.test(file.type || "");
  return api("/social/stories", { method: "POST", body: { media, is_video: isVideo } });
}

/** How one post performed. A number Instagram has not produced yet is null, which is not the same as 0. */
export async function fetchPostInsights(postId) {
  const data = await api(`/social/posts/${encodeURIComponent(postId)}/insights`);
  return data?.metrics || {};
}

/** The questions customers can tap to start a chat (Instagram "Ice Breakers"). */
export async function fetchIceBreakers() {
  return (await api("/social/ice-breakers")).questions || [];
}

export async function saveIceBreakers(questions) {
  return (await api("/social/ice-breakers", { method: "PUT", body: { questions } })).questions || [];
}
