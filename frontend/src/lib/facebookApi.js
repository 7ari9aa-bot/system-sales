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
  maxPictureBytes: 4 * 1024 * 1024,
  // Pictures in one post. Meta takes more, but a longer album fails often; the server holds the same cap.
  maxPictures: 10,
};

// What the Pages API takes for a picture. The server reads the real type from the file's bytes;
// this only keeps an obviously wrong file from being sent at all.
export const FB_PICTURE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"];

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

/** How many comments a post shows before "View more comments", and each click opens. */
export const COMMENTS_PER_STEP = 5;

/** The slice of a post's comments to draw after `steps` clicks of "View more comments".
 *  The newest stay in view, as on Facebook; `hidden` is what is still folded away and `next` how many
 *  the next click opens. */
export function commentWindow(comments, steps) {
  const list = comments || [];
  const size = COMMENTS_PER_STEP * (1 + Math.max(0, steps || 0));
  const shown = list.length > size ? list.slice(list.length - size) : list;
  const hidden = list.length - shown.length;
  return { shown, hidden, next: Math.min(COMMENTS_PER_STEP, hidden) };
}

/** The orders Facebook's comment menu offers. "Most relevant" is Facebook's own ranking and the Graph API
 *  does not give it for a Page's comments, so it keeps the API's order (oldest first); "Newest" and
 *  "All comments" (oldest first) are real orders on our own copy of the thread. */
export const COMMENT_SORTS = [
  { id: "relevant", ar: "الأكثر ملاءمة", en: "Most relevant" },
  { id: "newest", ar: "الأحدث", en: "Newest" },
  { id: "all", ar: "كل التعليقات", en: "All comments" },
];

const commentTime = (c) => {
  const t = new Date(c?.commentedAt || 0).getTime();
  return Number.isFinite(t) ? t : 0;
};

/** The thread in the chosen order. Replies stay under their parent and are ordered the same way.
 *  Returns new arrays; the input is untouched. An unknown id keeps the incoming order. */
export function sortComments(comments, sortId) {
  const list = Array.isArray(comments) ? comments : [];
  const dir = sortId === "newest" ? -1 : sortId === "all" ? 1 : 0;
  if (!dir) return list.map((c) => ({ ...c, replies: [...(c.replies || [])] }));
  const by = (a, b) => dir * (commentTime(a) - commentTime(b));
  return [...list].sort(by).map((c) => ({ ...c, replies: [...(c.replies || [])].sort(by) }));
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
        authorRef: c.author_ref || null,
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

/** A picked file as the base64 the server takes. Rejects when the browser cannot read it. */
export async function readPictureAsBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  // Chunked: spreading a few MB into one String.fromCharCode call overflows the call stack.
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** The album after picking more files: what was there, then the new ones, without a file picked twice,
 *  cut at the album limit. The result's `left` counts the files that did not fit. */
export function addPictures(current, picked) {
  const out = [...(current || [])];
  let left = 0;
  for (const file of Array.from(picked || [])) {
    if (out.some((f) => f.name === file.name && f.size === file.size && f.type === file.type)) continue;
    if (out.length >= FB_LIMITS.maxPictures) left += 1;
    else out.push(file);
  }
  out.left = left;
  return out;
}

// ---- Reactions. Meta lets a Page READ every kind but WRITE only a like, so these are for display. ----
export const REACTION_KINDS = ["LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY"];
export const REACTION_LABEL = {
  LIKE: { ar: "أعجبني", en: "Like" },
  LOVE: { ar: "أحببته", en: "Love" },
  HAHA: { ar: "هاها", en: "Haha" },
  WOW: { ar: "واو", en: "Wow" },
  SAD: { ar: "أحزنني", en: "Sad" },
  ANGRY: { ar: "أغضبني", en: "Angry" },
};

/** The kinds that have any reactions, most used first (ties in Facebook's order), at most three:
 *  the little icons beside the total in a post's summary line. */
export function topReactions(kinds, max = 3) {
  return REACTION_KINDS.map((kind, order) => ({ kind, count: Number(kinds?.[kind]) || 0, order }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.count - a.count || a.order - b.order)
    .slice(0, max)
    .map(({ kind, count }) => ({ kind, count }));
}

/** One post's or comment's reactions by kind, read from Facebook when asked for. */
export async function fetchReactionBreakdown(objectId) {
  const out = await api(`/facebook/objects/${enc(objectId)}/reactions`);
  return { total: out.total || 0, kinds: out.kinds || {} };
}

export async function publishFacebookPost({ message, link, picture, pictures, scheduleAt }) {
  const album = pictures || [];
  const hasPictures = !!picture || album.length > 0;
  return api("/facebook/posts", {
    method: "POST",
    body: {
      message: (message || "").trim() || null,
      link: hasPictures ? null : (link || "").trim() || null,
      picture: picture ? await readPictureAsBase64(picture) : null,
      // Only an album adds the field, so a text, link or single-picture post is sent exactly as it was.
      ...(album.length ? { pictures: await Promise.all(album.map(readPictureAsBase64)) } : {}),
      schedule_at: scheduleAt ? new Date(scheduleAt).toISOString() : null,
    },
  });
}

export const editFacebookPost = (postId, message) =>
  api(`/facebook/posts/${enc(postId)}`, { method: "PATCH", body: { message } });
export const deleteFacebookPost = (postId) => api(`/facebook/posts/${enc(postId)}`, { method: "DELETE" });

/** A comment on a post, or a reply when `objectId` is a comment. `mention` is the ids of people who
 *  commented, to tag (Meta's @mention); left out, the body is just the text. */
export const commentOn = (objectId, text, mention) =>
  api(`/facebook/objects/${enc(objectId)}/comments`, {
    method: "POST",
    body: mention?.length ? { text, mention } : { text },
  });

/** The ids a reply tags. Facebook opens a reply with the person's name in it, so a public reply tags
 *  the commenter unless the owner removed the name. A private reply goes to one inbox and tags nobody. */
export function replyMention(comment, { tagged, privateReply }) {
  if (privateReply || !tagged) return undefined;
  const handle = mentionHandle(comment);
  return handle ? [handle.id] : undefined;
}

/** Who a reply to this comment can tag: the person who wrote it. The Page itself and anyone whose id
 *  the server did not give cannot be tagged, so Facebook's pre-filled name is simply not offered. */
export function mentionHandle(comment) {
  if (!comment || comment.isPage || !comment.authorRef) return null;
  return { id: comment.authorRef, label: comment.author };
}
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
export function facebookPostProblem({ message = "", link = "", picture = null, pictures = [], scheduleAt = "" }, lang = "ar", now = Date.now()) {
  const ar = lang === "ar";
  const text = message.trim();
  const url = link.trim();
  const files = [...(picture ? [picture] : []), ...(pictures || [])];
  if (files.length > FB_LIMITS.maxPictures) return ar ? `المنشور يحمل ${FB_LIMITS.maxPictures} صور كحد أقصى` : `A post carries at most ${FB_LIMITS.maxPictures} pictures`;
  if (files.length) {
    for (const file of files) {
      if (!FB_PICTURE_TYPES.includes(file.type)) return ar ? "الصورة يجب أن تكون JPEG أو PNG أو GIF أو BMP أو WEBP" : "The picture must be a JPEG, PNG, GIF, BMP or WEBP";
      if (file.size > FB_LIMITS.maxPictureBytes) return ar ? "الصورة أكبر من 4 ميغابايت" : "The picture is larger than 4 MB";
    }
    if (url) return ar ? "المنشور يحمل صورة أو رابطًا، ليس الاثنين" : "A post carries a picture or a link, not both";
  } else if (!text && !url) return ar ? "اكتب نصًا أو أضف صورة أو رابطًا" : "Write something, or add a picture or a link";
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

// ---- Insights charts: Meta sends one value per day for each metric ----
/** A metric's days in date order, as {day: "YYYY-MM-DD", value}. A day without a number is left out;
 *  a real zero stays. */
export function dailySeries(metric) {
  return (metric?.values || [])
    .filter((v) => typeof v?.value === "number" && v.end_time)
    .map((v) => ({ day: String(v.end_time).slice(0, 10), value: v.value }))
    .sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
}

/** The SVG path of a series inside a width x height box: `line` for the stroke, `area` closed down to
 *  the floor for the fill. The highest value sits at the top; a flat series sits mid-height. */
export function chartPath(series, width, height) {
  if (!series.length) return { line: "", area: "" };
  const values = series.map((p) => p.value);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const x = (i) => (series.length === 1 ? width / 2 : (i / (series.length - 1)) * width);
  const y = (v) => (max === min ? height / 2 : height - ((v - min) / (max - min)) * height);
  const pts = series.map((p, i) => `${i ? "L" : "M"}${+x(i).toFixed(2)},${+y(p.value).toFixed(2)}`);
  const line = pts.join("");
  return { line, area: `${line}L${+x(series.length - 1).toFixed(2)},${height}L${+x(0).toFixed(2)},${height}Z` };
}

// ---- Reels and Stories (Meta: "Reels Publishing API", "Facebook Stories API") ----
// The rules are Meta's. The server checks the real file again from its own bytes; this keeps a
// file Meta would refuse from being uploaded (a video can be tens of MB) in the first place.
export const FB_VIDEO = {
  maxBytes: 200 * 1024 * 1024,
  minWidth: 540,
  minHeight: 960,
  ratio: 9 / 16,
  ratioTolerance: 0.02,
  minSeconds: 3,
  reelMaxSeconds: 90,
  storyMaxSeconds: 60,
  storyPhotoMaxBytes: 10 * 1024 * 1024,
  reelsPerDay: 30,
  scheduleMinMinutes: 10,
  scheduleMaxDays: 29,
  // The server holds the request while Facebook processes the video (up to 3 minutes) on top of
  // the upload itself. Cut off earlier, the Reel could still go live and look like a failure,
  // and a second try would post it twice.
  requestTimeoutMs: 6 * 60 * 1000,
};
export const FB_STORY_PHOTO_TYPES = ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/tiff"];

/** The size and length of a picked video as the browser plays it (a sideways phone video is already turned). */
export function readVideoInfo(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const el = document.createElement("video");
    const done = (fn, value) => { URL.revokeObjectURL(url); el.removeAttribute("src"); el.load(); fn(value); };
    el.preload = "metadata";
    el.muted = true;
    el.onloadedmetadata = () => done(resolve, { width: el.videoWidth, height: el.videoHeight, seconds: el.duration });
    el.onerror = () => done(reject, new Error("unreadable"));
    el.src = url;
  });
}

/** Why this file cannot be a Reel (kind "reel") or a Story (kind "story"), or "" when it can. `info` is readVideoInfo's answer. */
export function facebookVideoProblem(file, info, kind, lang = "ar") {
  const ar = lang === "ar";
  const what = kind === "reel" ? (ar ? "الريل" : "A Reel") : (ar ? "الستوري" : "A Story");
  if (!file) return ar ? "اختر ملفًا" : "Pick a file";
  if (file.type !== "video/mp4") return ar ? "فيسبوك يقبل فيديو mp4 فقط" : "Facebook takes only mp4 video";
  if (file.size > FB_VIDEO.maxBytes) return ar ? "الفيديو أكبر من 200 ميغابايت" : "The video is larger than 200 MB";
  if (!info) return ar ? "تعذّرت قراءة الفيديو" : "The video could not be read";
  const { width, height, seconds } = info;
  if (!width || !height || !Number.isFinite(seconds)) return ar ? "تعذّرت قراءة الفيديو" : "The video could not be read";
  if (width < FB_VIDEO.minWidth || height < FB_VIDEO.minHeight) {
    return ar ? `${what} لا يقل عن ${FB_VIDEO.minWidth} × ${FB_VIDEO.minHeight}، وهذا ${width} × ${height}` : `${what} must be at least ${FB_VIDEO.minWidth} x ${FB_VIDEO.minHeight}; this one is ${width} x ${height}`;
  }
  if (Math.abs(width / height - FB_VIDEO.ratio) > FB_VIDEO.ratioTolerance) {
    return ar ? `${what} طولي بنسبة 9:16، وهذا ${width} × ${height}` : `${what} must be tall (9:16); this one is ${width} x ${height}`;
  }
  const max = kind === "reel" ? FB_VIDEO.reelMaxSeconds : FB_VIDEO.storyMaxSeconds;
  if (seconds < FB_VIDEO.minSeconds) return ar ? `${what} لا يقل عن ${FB_VIDEO.minSeconds} ثوانٍ` : `${what} is at least ${FB_VIDEO.minSeconds} seconds`;
  if (seconds > max) return ar ? `${what} لا يزيد عن ${max} ثانية، وهذا ${Math.round(seconds)}` : `${what} is at most ${max} seconds; this one is ${Math.round(seconds)}`;
  return "";
}

/** Why this picture cannot be a Story, or "". */
export function facebookStoryPhotoProblem(file, lang = "ar") {
  const ar = lang === "ar";
  if (!file) return ar ? "اختر ملفًا" : "Pick a file";
  if (!FB_STORY_PHOTO_TYPES.includes(file.type)) return ar ? "صورة الستوري JPEG أو PNG أو GIF أو BMP أو TIFF" : "A Story picture must be a JPEG, PNG, GIF, BMP or TIFF";
  if (file.size > FB_VIDEO.storyPhotoMaxBytes) return ar ? "صورة الستوري أكبر من 10 ميغابايت" : "A Story picture is larger than 10 MB";
  return "";
}

/** Why the Reel's time cannot be used, or "" (10 minutes to 29 days away). */
export function facebookReelScheduleProblem(scheduleAt, lang = "ar", now = Date.now()) {
  if (!scheduleAt) return "";
  const ar = lang === "ar";
  const at = new Date(scheduleAt).getTime();
  if (!Number.isFinite(at)) return ar ? "موعد النشر غير صالح" : "The schedule time is not valid";
  const mins = (at - now) / 60000;
  if (mins < FB_VIDEO.scheduleMinMinutes) return ar ? "الجدولة بعد 10 دقائق على الأقل من الآن" : "Schedule at least 10 minutes from now";
  if (mins > FB_VIDEO.scheduleMaxDays * 1440) return ar ? "جدولة الريل خلال 29 يومًا كحد أقصى" : "Schedule a Reel within 29 days at most";
  return "";
}

export async function fetchFacebookReels({ limit = 25 } = {}) {
  return (await api(`/facebook/reels?limit=${limit}`)).items || [];
}
export async function fetchFacebookStories() {
  return (await api("/facebook/stories")).items || [];
}

/** Publish a Reel: the raw mp4 is the body; the text travels percent-encoded so Arabic survives a header. */
export function publishFacebookReel({ file, description, title, scheduleAt, aiGenerated, signal }) {
  return api("/facebook/reels", {
    method: "POST",
    body: file,
    rawBody: true,
    contentType: "video/mp4",
    signal,
    timeoutMs: FB_VIDEO.requestTimeoutMs,
    headers: {
      ...((description || "").trim() ? { "X-Description": enc(description.trim()) } : {}),
      ...((title || "").trim() ? { "X-Title": enc(title.trim()) } : {}),
      ...(scheduleAt ? { "X-Schedule-At": new Date(scheduleAt).toISOString() } : {}),
      ...(aiGenerated ? { "X-AI-Generated": "true" } : {}),
    },
  });
}

/** Publish a Story from a video (video/mp4) or a picture; its own type tells the server which. */
export function publishFacebookStory({ file, signal }) {
  return api("/facebook/stories", { method: "POST", body: file, rawBody: true, contentType: file.type, signal, timeoutMs: FB_VIDEO.requestTimeoutMs });
}

/**
 * What stops a Reel or a Story from being sent, in one place so the dialog and its tests agree.
 * `state`: { kind, file, info, reading, readError, scheduleOn, scheduleAt }. "" means it can go.
 */
export function facebookReelStoryProblem({ kind, file, info = null, reading = false, readError = "", scheduleOn = false, scheduleAt = "" }, lang = "ar", now = Date.now()) {
  const ar = lang === "ar";
  if (!file) return ar ? "اختر فيديو" : "Pick a video";
  if (readError) return readError;
  if (String(file.type).startsWith("image/")) return kind === "reel" ? (ar ? "الريل فيديو فقط" : "A Reel is a video") : facebookStoryPhotoProblem(file, lang);
  if (reading) return ar ? "جارٍ قراءة الفيديو..." : "Reading the video...";
  const fileProblem = facebookVideoProblem(file, info, kind, lang);
  if (fileProblem) return fileProblem;
  return kind === "reel" && scheduleOn ? facebookReelScheduleProblem(scheduleAt, lang, now) : "";
}

/** The words shown when publishing failed. After a dropped connection the server may still have posted it, so the agent is told to look before trying again. */
export function facebookPublishFailure(error, lang = "ar") {
  const ar = lang === "ar";
  if (error?.code === "timeout" || error?.code === "network") {
    return ar
      ? "انقطع الاتصال قبل أن نعرف النتيجة. قد يكون نُشر، راجع القائمة قبل المحاولة مرة أخرى."
      : "The connection dropped before we knew the result. It may have been posted; check the list before trying again.";
  }
  return error?.message || (ar ? "تعذّر النشر" : "Could not publish");
}
