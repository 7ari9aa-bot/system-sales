import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Heart, Image as ImageIcon, MessageCircle, MoreHorizontal, Send, Video } from "lucide-react";
import { cn } from "@/lib/utils";

const POST_LIST_MIN_WIDTH = 260;
const POST_LIST_MAX_WIDTH = 430;
const POST_LIST_DEFAULT_WIDTH = 310;

function readPostListPreference(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
}

export default function InstagramPostsWorkspace({ posts = [], lang = "ar", onReply }) {
  const isArabic = lang === "ar";
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState(posts[0]?.id || null);
  const [replyTo, setReplyTo] = useState(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [postListWidth, setPostListWidth] = useState(() => {
    const width = Number(readPostListPreference("fihrist.instagramPosts.listWidth", POST_LIST_DEFAULT_WIDTH));
    return Number.isFinite(width) ? Math.min(POST_LIST_MAX_WIDTH, Math.max(POST_LIST_MIN_WIDTH, width)) : POST_LIST_DEFAULT_WIDTH;
  });
  const [postListCollapsed, setPostListCollapsed] = useState(() => Boolean(readPostListPreference("fihrist.instagramPosts.listCollapsed", false)));
  const [isNarrowViewport, setIsNarrowViewport] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 1023px)").matches);
  const [isResizing, setIsResizing] = useState(false);
  const resizeState = useRef(null);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const update = () => setIsNarrowViewport(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  useEffect(() => {
    try { window.localStorage.setItem("fihrist.instagramPosts.listWidth", JSON.stringify(postListWidth)); } catch { /* Storage can be disabled. */ }
  }, [postListWidth]);
  useEffect(() => {
    try { window.localStorage.setItem("fihrist.instagramPosts.listCollapsed", JSON.stringify(postListCollapsed)); } catch { /* Storage can be disabled. */ }
  }, [postListCollapsed]);
  const startResize = (event) => {
    if (isNarrowViewport || postListCollapsed) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    resizeState.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: postListWidth };
    setIsResizing(true);
  };
  const moveResize = (event) => {
    if (!resizeState.current || resizeState.current.pointerId !== event.pointerId) return;
    const delta = event.clientX - resizeState.current.startX;
    setPostListWidth(Math.min(POST_LIST_MAX_WIDTH, Math.max(POST_LIST_MIN_WIDTH, resizeState.current.startWidth + delta)));
  };
  const finishResize = (event) => {
    if (!resizeState.current || (event?.pointerId != null && resizeState.current.pointerId !== event.pointerId)) return;
    resizeState.current = null;
    setIsResizing(false);
  };
  const resizeWithKeyboard = (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setPostListWidth((width) => Math.min(POST_LIST_MAX_WIDTH, Math.max(POST_LIST_MIN_WIDTH, width + (event.key === "ArrowRight" ? 16 : -16))));
    } else if (event.key === "Home") {
      event.preventDefault(); setPostListWidth(POST_LIST_MIN_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault(); setPostListWidth(POST_LIST_MAX_WIDTH);
    }
  };
  const visiblePosts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return posts;
    return posts.filter((post) => `${post.text} ${(post.comments || []).map((comment) => `${comment.author} ${comment.text}`).join(" ")}`.toLocaleLowerCase().includes(needle));
  }, [posts, query]);
  const selected = posts.find((post) => post.id === activeId) || visiblePosts[0] || posts[0] || null;

  function submitReply(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !selected || sending) return;
    setSending(true);
    onReply?.(replyTo?.id || null, selected.id, text);
    setDraft("");
    setReplyTo(null);
    setSending(false);
  }

  return (
    <section dir="ltr" className="flex min-h-0 flex-1 flex-col bg-[#fafafa] text-[#262626]">
      <div style={!isNarrowViewport && !postListCollapsed ? { "--instagram-post-list-width": `${postListWidth}px` } : undefined} className={cn("grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(180px,34dvh)_minmax(0,1fr)] lg:grid-rows-1", !isNarrowViewport && (postListCollapsed ? "lg:grid-cols-[48px_minmax(0,1fr)]" : "lg:grid-cols-[var(--instagram-post-list-width)_6px_minmax(0,1fr)]"))}>
        <aside dir={isArabic ? "rtl" : "ltr"} aria-label={isArabic ? "قائمة منشورات الصفحة" : "Page post list"} className={cn("flex min-h-0 min-w-0 flex-col border-b border-[#dbdbdb] bg-white lg:border-b-0 lg:border-r", postListCollapsed && !isNarrowViewport && "items-center")}>
          {postListCollapsed && !isNarrowViewport ? <div className="flex h-full w-full flex-col items-center gap-3 py-3">
            <button type="button" onClick={() => setPostListCollapsed(false)} aria-label={isArabic ? "توسيع قائمة المنشورات" : "Expand post list"} title={isArabic ? "توسيع قائمة المنشورات" : "Expand post list"} className="grid h-9 w-9 place-items-center rounded-full text-[#8e8e8e] hover:bg-[#f5f5f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6]"><ChevronRight className="h-4 w-4" /></button>
            <span className="rounded-full bg-[#fff2f6] px-2 py-1 text-[10px] font-semibold text-[#c13584]">{visiblePosts.length}</span>
          </div> : <>
          <div className="shrink-0 border-b border-[#efefef] px-4 pb-3 pt-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h1 className="text-[17px] font-semibold tracking-[-0.02em]">{isArabic ? "منشورات الصفحة" : "Page posts"}</h1>
                <p className="mt-1 text-[12px] text-[#8e8e8e]">{isArabic ? `${posts.length} منشورات · أحدث التفاعلات` : `${posts.length} posts · Latest activity`}</p>
              </div>
              <div className="flex items-center gap-1.5"><span className="grid h-9 w-9 place-items-center rounded-full bg-[#fff2f6] text-[#d62976]"><MessageCircle className="h-[17px] w-[17px]" /></span><button type="button" onClick={() => setPostListCollapsed(true)} aria-label={isArabic ? "طي قائمة المنشورات" : "Collapse post list"} title={isArabic ? "طي قائمة المنشورات" : "Collapse post list"} className="hidden h-8 w-8 place-items-center rounded-full text-[#8e8e8e] hover:bg-[#f5f5f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6] lg:grid"><ChevronLeft className="h-4 w-4" /></button></div>
            </div>
            <label className="mt-3 flex h-9 items-center gap-2 rounded-lg bg-[#efefef] px-3 text-[#8e8e8e] focus-within:ring-2 focus-within:ring-[#0095f6]/30">
              <MessageCircle className="h-4 w-4 shrink-0" />
              <input value={query} onChange={(event) => setQuery(event.target.value)} dir={isArabic ? "rtl" : "ltr"} placeholder={isArabic ? "ابحث في المنشورات والتعليقات" : "Search posts and comments"} aria-label={isArabic ? "ابحث في المنشورات والتعليقات" : "Search posts and comments"} className="min-w-0 flex-1 bg-transparent text-[13px] text-[#262626] outline-none placeholder:text-[#8e8e8e]" />
            </label>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {visiblePosts.length === 0 ? <p className="px-5 py-8 text-center text-[13px] text-[#8e8e8e]">{isArabic ? "لا توجد منشورات مطابقة" : "No matching posts"}</p> : visiblePosts.map((post) => {
              const active = selected?.id === post.id;
              return (
                <button key={post.id} type="button" aria-pressed={active} onClick={() => { setActiveId(post.id); setReplyTo(null); }} className={cn("flex w-full items-center gap-3 border-b border-[#f2f2f2] px-3 py-3 text-left transition-colors hover:bg-[#fafafa] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0095f6]", active && "bg-[#f5f9ff] shadow-[inset_3px_0_0_#0095f6]")}>
                  <PostThumbnail post={post} />
                  <span className="min-w-0 flex-1">
                    <span dir="auto" className="block line-clamp-2 text-[13px] leading-[1.6] text-[#262626]">{post.text}</span>
                    <span className="mt-2 flex items-center gap-2 text-[11.5px] text-[#8e8e8e]">
                      <span dir="auto">{post.timeLabel}</span><span aria-hidden="true">·</span><MessageCircle className="h-3 w-3" /><span>{post.comments?.length || 0}</span>
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
          </>}
        </aside>

        {!isNarrowViewport && !postListCollapsed && <div role="separator" aria-label={isArabic ? "تغيير عرض قائمة منشورات إنستجرام" : "Resize Instagram post list"} aria-orientation="vertical" aria-valuemin={POST_LIST_MIN_WIDTH} aria-valuemax={POST_LIST_MAX_WIDTH} aria-valuenow={postListWidth} tabIndex={0} onPointerDown={startResize} onPointerMove={moveResize} onPointerUp={finishResize} onPointerCancel={finishResize} onLostPointerCapture={finishResize} onKeyDown={resizeWithKeyboard} className={cn("group relative z-10 -ml-[3px] w-[6px] cursor-col-resize touch-none select-none bg-transparent outline-none", isResizing && "bg-[#0095f6]/10")}><span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[#dbdbdb] transition-colors group-hover:bg-[#0095f6] group-focus-visible:bg-[#0095f6]" /></div>}

        <main dir={isArabic ? "rtl" : "ltr"} className="flex min-h-0 min-w-0 flex-col bg-[#fafafa]">
          {!selected ? (
            <div className="grid min-h-[280px] flex-1 place-items-center p-8 text-center">
              <div className="max-w-xs"><span className="mx-auto grid h-14 w-14 place-items-center rounded-full border border-[#dbdbdb] text-[#8e8e8e]"><MessageCircle className="h-6 w-6" /></span><h2 className="mt-4 text-[15px] font-semibold">{isArabic ? "اختار منشور لمراجعة التعليقات" : "Choose a post to review comments"}</h2><p className="mt-2 text-[12px] leading-5 text-[#8e8e8e]">{isArabic ? "هتظهر هنا تفاصيل المنشور والتعليقات والردود." : "The post, comments, and replies will appear here."}</p></div>
            </div>
          ) : (
            <>
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                <article className="mx-auto w-full max-w-[860px] px-4 pb-4 pt-5 sm:px-7">
                  <div className="overflow-hidden rounded-[10px] border border-[#dbdbdb] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                    <div className="flex items-center gap-3 px-4 py-3">
                      <div className="rounded-full bg-[conic-gradient(from_45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5,#feda75)] p-[2px]"><img src={selected.accountAvatarUrl || "/fihrist-mark.svg"} alt="" className="h-9 w-9 rounded-full border-2 border-white bg-white object-cover" /></div>
                      <div className="min-w-0 flex-1"><p dir="ltr" className="truncate text-[14px] font-semibold">{selected.accountName || "fihrist.store"}</p><p className="mt-0.5 text-[12px] text-[#8e8e8e]">{selected.timeLabel}</p></div>
                      <button type="button" aria-label={isArabic ? "خيارات المنشور" : "Post options"} className="rounded-full p-2 text-[#262626] hover:bg-[#f5f5f5]"><MoreHorizontal className="h-5 w-5" /></button>
                    </div>
                    {selected.mediaUrl && <div className="flex max-h-[300px] items-center justify-center overflow-hidden bg-[#f3f3f3] sm:max-h-[360px]"><img src={selected.mediaUrl} alt={isArabic ? "صورة المنشور" : "Post media"} className="max-h-[300px] w-full object-contain sm:max-h-[360px]" /></div>}
                    <div dir={isArabic ? "rtl" : "ltr"} className="px-4 pb-3 pt-3">
                      <div className="mb-2 flex items-center gap-4 text-[#262626]"><Heart className="h-[19px] w-[19px]" /><MessageCircle className="h-[19px] w-[19px]" /><Send className="h-[18px] w-[18px]" /></div>
                      <p className="text-[13px] font-semibold">{Number(selected.likes || 0).toLocaleString(isArabic ? "ar-EG" : "en-US")} {isArabic ? "إعجاب" : "likes"}</p>
                      <p className="mt-2 text-[14px] leading-[1.7]"><bdi dir="auto" className="me-1 font-semibold">{selected.accountName || "fihrist.store"}</bdi><span dir="auto">{selected.text}</span></p>
                      <div className="mt-3 flex items-center justify-between border-t border-[#efefef] pt-2.5 text-[12px] text-[#8e8e8e]"><span>{isArabic ? "التعليقات" : "Comments"} <b className="font-medium text-[#262626]">{countComments(selected.comments)}</b></span><span>{isArabic ? "الأحدث" : "Most recent"}</span></div>
                    </div>
                  </div>
                </article>

                <section aria-label={isArabic ? "تعليقات المنشور" : "Post comments"} dir={isArabic ? "rtl" : "ltr"} className="mx-auto w-full max-w-[860px] px-4 pb-5 sm:px-7">
                  {(selected.comments || []).length ? <div className="space-y-5">{selected.comments.map((comment) => <Comment key={comment.id} comment={comment} isArabic={isArabic} onReply={() => { setReplyTo(comment); requestAnimationFrame(() => document.getElementById("instagram-comment-reply")?.focus()); }} />)}</div> : <p className="py-8 text-center text-[13px] text-[#8e8e8e]">{isArabic ? "لسه مفيش تعليقات على المنشور ده." : "No comments on this post yet."}</p>}
                </section>
              </div>

              <form onSubmit={submitReply} dir={isArabic ? "rtl" : "ltr"} className="shrink-0 border-t border-[#dbdbdb] bg-white px-4 py-3 sm:px-7">
                <div className="mx-auto max-w-[860px]">
                  {replyTo && <div className="mb-2 flex items-center justify-between text-[12px] text-[#8e8e8e]"><span>{isArabic ? <>الرد على <b className="font-semibold text-[#262626]">{replyTo.author}</b></> : <>Replying to <b className="font-semibold text-[#262626]">{replyTo.handle || replyTo.author}</b></>}</span><button type="button" onClick={() => setReplyTo(null)} className="rounded px-1 text-[#0095f6] hover:underline">{isArabic ? "إلغاء" : "Cancel"}</button></div>}
                  <div className="flex min-h-10 items-center gap-3 rounded-full border border-[#dbdbdb] bg-white px-3 py-1.5 focus-within:border-[#a8a8a8]">
                    <button type="button" disabled aria-label={isArabic ? "إضافة صورة للتعليق غير متاحة في العرض التجريبي" : "Attach media unavailable in demo"} className="shrink-0 text-[#8e8e8e] disabled:opacity-60"><ImageIcon className="h-[17px] w-[17px]" /></button>
                    <textarea id="instagram-comment-reply" rows={1} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} dir="auto" placeholder={replyTo ? (isArabic ? "اكتب ردك..." : "Write a reply...") : (isArabic ? "أضف تعليقًا..." : "Add a comment...")} className="max-h-24 min-h-6 min-w-0 flex-1 resize-y bg-transparent py-1.5 text-[14px] leading-[1.6] outline-none placeholder:text-[#8e8e8e]" />
                    <button type="submit" disabled={!draft.trim() || sending} className="shrink-0 px-1 text-[13px] font-semibold text-[#0095f6] hover:text-[#00376b] disabled:cursor-not-allowed disabled:opacity-40">{isArabic ? "نشر" : "Post"}</button>
                  </div>
                </div>
              </form>
            </>
          )}
        </main>
      </div>
    </section>
  );
}

function PostThumbnail({ post }) {
  return post.mediaUrl ? <span className="relative grid h-[58px] w-[58px] shrink-0 place-items-center overflow-hidden rounded-md bg-[#f1f1f1]"><img src={post.mediaUrl} alt="" className="h-full w-full object-cover" />{post.mediaType === "video" && <Video className="absolute right-1 top-1 h-3.5 w-3.5 fill-white text-white drop-shadow" />}</span> : <span className="grid h-[58px] w-[58px] shrink-0 place-items-center rounded-md bg-[#fff2f6] text-[#d62976]"><ImageIcon className="h-5 w-5" /></span>;
}

function Comment({ comment, isArabic, onReply, nested = false }) {
  return (
    <div className={cn("flex items-start gap-2.5", nested && "ms-10 border-s border-[#efefef] ps-3")}>
      <img src={comment.avatarUrl || "/fihrist-mark.svg"} alt="" className="mt-0.5 h-9 w-9 shrink-0 rounded-full border border-[#efefef] bg-white object-cover" />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] leading-[1.7] text-[#262626]">
          <bdi dir="auto" className="me-1 inline-block font-bold">{comment.handle || comment.author}</bdi>
          <span dir="auto" className="[unicode-bidi:isolate]">{comment.text}</span>
          {comment.isAgent && <span dir="auto" className="ms-1.5 inline-flex translate-y-[-1px] items-center rounded-full bg-[#fce8f0] px-2 py-0.5 text-[10px] font-semibold leading-4 text-[#c13584]">{isArabic ? "رد تلقائي" : "Auto reply"}</span>}
        </div>
        <div className="mt-1 flex items-center gap-3 text-[12px] font-medium text-[#737373]">
          <span>{comment.timeLabel}</span>{comment.likes > 0 && <span>{comment.likes} {isArabic ? "إعجاب" : "likes"}</span>}
          <button type="button" onClick={onReply} className="font-semibold hover:text-[#262626] focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6]">{isArabic ? "رد" : "Reply"}</button>
          {comment.isPage && !comment.isAgent && <span className="text-[#8e8e8e]">{isArabic ? "أنت" : "You"}</span>}
        </div>
        {(comment.replies || []).length > 0 && <div className="mt-3 space-y-3">{comment.replies.map((reply) => <Comment key={reply.id} comment={reply} isArabic={isArabic} nested onReply={onReply} />)}</div>}
      </div>
      <button type="button" disabled aria-label={isArabic ? "إعجاب غير متاح في العرض التجريبي" : "Like unavailable in demo"} className="mt-1 shrink-0 text-[#8e8e8e] disabled:opacity-60"><Heart className="h-4 w-4" /></button>
    </div>
  );
}

function countComments(comments = []) {
  return comments.reduce((sum, comment) => sum + 1 + (comment.replies?.length || 0), 0);
}
