import React, { useEffect, useState } from "react";
import { ArrowLeft, Facebook, Globe2, MessageCircle, MoreHorizontal, Search, Send, Share2, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/utils";

function Avatar({ src, name, size = "h-9 w-9" }) {
  const [failed, setFailed] = useState(false);
  const initials = String(name || "F").trim().slice(0, 1);
  return src && !failed
    ? <img src={src} alt="" className={cn(size, "shrink-0 rounded-full object-cover")} onError={() => setFailed(true)} />
    : <span className={cn(size, "grid shrink-0 place-items-center rounded-full bg-[#e7f3ff] text-sm font-semibold text-[#0866ff]")}>{initials}</span>;
}

function isAutomatedReply(reply) {
  return Boolean(reply.isAgentReply || reply.isAgent || reply.isAutomated || reply.isAutoReply || reply.authorType === "agent" || reply.source === "agent" || reply.replyType === "agent" || reply.origin === "agent");
}

function CommentThread({ comment, pageName, onReply, lang }) {
  const [replyOpen, setReplyOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [liked, setLiked] = useState(false);
  const isArabic = lang === "ar";
  const submit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    onReply(comment.id, text);
    setDraft("");
    setReplyOpen(false);
    setNotice(isArabic ? "تمت إضافة رد الصفحة محليًا" : "Page reply added locally");
    window.setTimeout(() => setNotice(""), 2200);
  };
  const renderBubble = (author, text, isPage = false) => (
    <div className="inline-block max-w-full rounded-[18px] bg-[#f0f2f5] px-3 py-2 text-[13px] leading-[1.38] text-[#050505]">
      <span className="font-semibold">{author}</span>
      {isPage && <span className="ms-1 text-[10px] font-medium text-[#65676b]">· {isArabic ? "الصفحة" : "Page"}</span>}
      <span dir="auto" className="whitespace-pre-wrap break-words">{" "}{text}</span>
    </div>
  );
  const renderActions = (timeLabel, likedCount, isTopLevel = false) => (
    <div className="mt-0.5 flex min-h-5 items-center gap-2 px-3 text-[11px] font-semibold leading-4 text-[#65676b]">
      {isTopLevel ? <button type="button" aria-pressed={liked} onClick={() => setLiked((value) => !value)} className={cn("hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]", liked && "text-[#0866ff]")}>{isArabic ? "أعجبني" : "Like"}</button> : <span>{isArabic ? "أعجبني" : "Like"}</span>}
      <span aria-hidden="true">·</span>
      {isTopLevel ? <button type="button" onClick={() => { setReplyOpen((value) => !value); setNotice(""); }} className="hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]">{isArabic ? "رد" : "Reply"}</button> : <span>{isArabic ? "رد" : "Reply"}</span>}
      <span aria-hidden="true">·</span>
      <span className="font-normal">{timeLabel}</span>
      {likedCount > 0 && <span className="ms-auto inline-flex items-center gap-1 font-normal text-[#65676b]"><ThumbsUp className="h-3.5 w-3.5 fill-[#0866ff] text-white" />{likedCount + Number(isTopLevel && liked)}</span>}
    </div>
  );
  return (
    <div className="min-w-0">
      <div className="flex items-start gap-2">
        <Avatar src={comment.avatarUrl} name={comment.author} size="h-8 w-8" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
            {renderBubble(comment.author, comment.text, comment.isPage)}
            {isAutomatedReply(comment) && <span className="rounded-full bg-[#e7f3ff] px-1.5 py-0.5 text-[9px] font-semibold leading-3 text-[#0866ff]">{isArabic ? "رد تلقائي" : "Auto reply"}</span>}
          </div>
          {renderActions(comment.timeLabel, comment.likes || 0, true)}
        </div>
      </div>
      {(comment.replies || []).length > 0 && (
        <div className="mt-1.5 space-y-2 ps-8 sm:ps-10">
          {comment.replies.map((reply) => (
            <div key={reply.id} className="flex items-start gap-2">
              <Avatar src={reply.avatarUrl || (reply.isPage ? "/fihrist-mark.svg" : undefined)} name={reply.author} size="h-7 w-7" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                  {renderBubble(reply.author, reply.text, reply.isPage)}
                  {isAutomatedReply(reply) && <span className="rounded-full bg-[#e7f3ff] px-1.5 py-0.5 text-[9px] font-semibold leading-3 text-[#0866ff]">{isArabic ? "رد تلقائي" : "Auto reply"}</span>}
                </div>
                {renderActions(reply.timeLabel, reply.likes || 0)}
              </div>
            </div>
          ))}
        </div>
      )}
      {replyOpen && (
        <form onSubmit={submit} className="mt-2 flex gap-2 ps-8 sm:ps-10">
          <Avatar src="/fihrist-mark.svg" name={pageName} size="h-7 w-7" />
          <div className="flex min-w-0 flex-1 items-center rounded-full border border-[#e4e6eb] bg-white px-3 focus-within:border-[#0866ff]">
            <input autoFocus value={draft} onChange={(event) => setDraft(event.target.value)} dir={isArabic ? "rtl" : "ltr"} placeholder={isArabic ? "اكتب ردًا بصفتك الصفحة..." : "Reply as Page..."} className="min-w-0 flex-1 bg-transparent py-2 text-[12px] outline-none placeholder:text-[#8a8d91]" />
            <button type="submit" disabled={!draft.trim()} aria-label={isArabic ? "إرسال الرد" : "Send reply"} className="grid h-7 w-7 place-items-center rounded-full text-[#0866ff] hover:bg-[#e7f3ff] disabled:opacity-40"><Send className="h-4 w-4" /></button>
          </div>
        </form>
      )}
      {notice && <p role="status" className="mt-1 ps-8 text-[10.5px] text-[#237a57] sm:ps-10">{notice}</p>}
    </div>
  );
}

export default function FacebookPostsWorkspace({ posts = [], lang = "ar", onReply, onComment }) {
  const isArabic = lang === "ar";
  const [selectedPostId, setSelectedPostId] = useState(() => posts[0]?.id ?? null);
  const [search, setSearch] = useState("");
  const [likedPosts, setLikedPosts] = useState(() => new Set());
  const [commentingPost, setCommentingPost] = useState(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentNotice, setCommentNotice] = useState("");
  useEffect(() => {
    if (selectedPostId && !posts.some((post) => post.id === selectedPostId)) setSelectedPostId(posts[0]?.id ?? null);
  }, [posts, selectedPostId]);
  const selectedPost = posts.find((post) => post.id === selectedPostId) || null;
  const filteredPosts = posts.filter((post) => `${post.pageName || ""} ${post.text || ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const submitPageComment = (event, post) => {
    event.preventDefault();
    const text = commentDraft.trim();
    if (!text) return;
    onComment?.(post.id, text);
    setCommentDraft("");
    setCommentingPost(null);
    setCommentNotice(post.id);
    window.setTimeout(() => setCommentNotice((current) => current === post.id ? "" : current), 2200);
  };

  return (
    <section dir={isArabic ? "rtl" : "ltr"} aria-label={isArabic ? "منشورات صفحة فيسبوك وتعليقاتها" : "Facebook Page posts and comments"} className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[#f0f2f5]">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#d8dadf] bg-white px-4 py-2.5 sm:px-6">
        <div className="flex min-w-0 items-center gap-2.5">
          <Avatar src="/fihrist-mark.svg" name="FIHRIST" size="h-9 w-9" />
          <div className="min-w-0"><h2 className="truncate text-[14px] font-bold text-[#1c1e21]">{isArabic ? "منشورات الصفحة" : "Page posts"}</h2><p className="text-[11px] text-[#65676b]">{isArabic ? "التعليقات والردود العامة" : "Public comments and replies"}</p></div>
        </div>
        <div className="flex shrink-0 items-center gap-1 rounded-lg bg-[#e7f3ff] px-2.5 py-1.5 text-[11px] font-semibold text-[#0866ff]"><Facebook className="h-3.5 w-3.5" />{isArabic ? "فيسبوك" : "Facebook"}</div>
      </div>
      <div dir="ltr" className="flex min-h-0 flex-1 overflow-hidden">
        <aside dir={isArabic ? "rtl" : "ltr"} aria-label={isArabic ? "قائمة منشورات الصفحة" : "Page post list"} className={cn("flex w-full shrink-0 flex-col border-e border-[#d8dadf] bg-white md:w-[310px] lg:w-[350px]", selectedPost && "hidden md:flex")}>
          <div className="shrink-0 border-b border-[#e4e6eb] p-3">
            <label className="flex h-10 items-center gap-2 rounded-full bg-[#f0f2f5] px-3 text-[#65676b] focus-within:ring-2 focus-within:ring-[#0866ff]/40">
              <Search className="h-4 w-4 shrink-0" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={isArabic ? "ابحث في المنشورات" : "Search posts"} className="min-w-0 flex-1 bg-transparent text-[12px] text-[#1c1e21] outline-none placeholder:text-[#65676b]" />
            </label>
            <div className="mt-3 flex items-center justify-between px-1 text-[12px]">
              <h3 className="font-bold text-[#1c1e21]">{isArabic ? "منشورات الصفحة" : "Page posts"}</h3>
              <span className="text-[11px] text-[#65676b]">{filteredPosts.length}</span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {posts.length === 0 ? <p className="px-4 py-8 text-center text-[12px] text-[#65676b]">{isArabic ? "لا تتوفر منشورات لهذه الصفحة." : "No Page posts are available."}</p> : filteredPosts.length === 0 ? <p className="px-4 py-8 text-center text-[12px] text-[#65676b]">{isArabic ? "لا توجد منشورات مطابقة للبحث." : "No posts match your search."}</p> : filteredPosts.map((post) => {
              const count = (post.comments || []).reduce((sum, comment) => sum + 1 + (comment.replies || []).length, 0);
              return <button key={post.id} type="button" onClick={() => { setSelectedPostId(post.id); setCommentingPost(null); setCommentDraft(""); }} aria-current={selectedPostId === post.id ? "true" : undefined} className={cn("flex w-full items-start gap-2.5 border-b border-[#f0f2f5] px-3 py-3 text-start transition-colors hover:bg-[#f7f8fa] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0866ff]", selectedPostId === post.id && "bg-[#e7f3ff] hover:bg-[#e7f3ff]")}>
                <Avatar src={post.pageAvatarUrl} name={post.pageName} size="h-10 w-10" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2"><span className="truncate text-[12px] font-semibold text-[#1c1e21]">{post.pageName}</span><span className="shrink-0 text-[10px] text-[#65676b]">{post.timeLabel}</span></span>
                  <span className="mt-1 flex items-center gap-2">
                    {post.mediaUrl && <img src={post.mediaUrl} alt="" className="h-8 w-8 shrink-0 rounded-md object-cover" loading="lazy" />}
                    <span className="line-clamp-2 min-w-0 flex-1 text-[11px] leading-4 text-[#65676b]">{post.text}</span>
                  </span>
                  <span className="mt-1.5 flex items-center gap-1 text-[10px] text-[#65676b]"><MessageCircle className="h-3 w-3" />{count} {isArabic ? "تعليقات" : "comments"}</span>
                </span>
              </button>;
            })}
          </div>
          <p className="shrink-0 border-t border-[#e4e6eb] px-3 py-2 text-center text-[10px] text-[#65676b]">{isArabic ? "بيانات تجريبية محفوظة محليًا" : "Demo content stored locally"}</p>
        </aside>

        <div dir={isArabic ? "rtl" : "ltr"} className={cn("min-w-0 flex-1 flex-col bg-white", selectedPost ? "flex" : "hidden md:flex")}>
          {selectedPost ? (() => {
            const post = selectedPost;
            const liked = likedPosts.has(post.id);
            const totalComments = (post.comments || []).reduce((sum, comment) => sum + 1 + (comment.replies || []).length, 0);
            return <>
              <header className="flex shrink-0 items-center gap-2.5 border-b border-[#e4e6eb] bg-white px-3 py-2.5 sm:px-5">
                <button type="button" onClick={() => setSelectedPostId(null)} aria-label={isArabic ? "العودة إلى المنشورات" : "Back to posts"} className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#65676b] hover:bg-[#f0f2f5] md:hidden"><ArrowLeft className={cn("h-4 w-4", isArabic && "rotate-180")} /></button>
                <Avatar src={post.pageAvatarUrl} name={post.pageName} size="h-9 w-9" />
                <div className="min-w-0 flex-1"><h3 className="truncate text-[13px] font-bold text-[#1c1e21]">{post.pageName}</h3><p className="mt-0.5 flex items-center gap-1 text-[10.5px] text-[#65676b]"><span>{post.timeLabel}</span><span aria-hidden="true">·</span><Globe2 className="h-3 w-3" /></p></div>
                <button type="button" disabled aria-label={isArabic ? "المزيد غير متاح في العرض التجريبي" : "More options unavailable in this demo"} className="grid h-8 w-8 cursor-not-allowed place-items-center rounded-full text-[#8a8d91]"><MoreHorizontal className="h-5 w-5" /></button>
              </header>
              <div className="shrink-0 border-b border-[#e4e6eb] bg-white">
                <p dir="auto" className="max-h-28 overflow-y-auto whitespace-pre-wrap px-4 py-3 text-[13px] leading-[1.6] text-[#1c1e21] sm:px-5">{post.text}</p>
                {post.mediaUrl && <img src={post.mediaUrl} alt={isArabic ? "صورة من منشور الصفحة" : "Page post image"} className="max-h-52 w-full bg-[#f0f2f5] object-contain" loading="lazy" />}
                <div className="flex items-center justify-between px-4 py-2 text-[11px] text-[#65676b] sm:px-5">
                  <span className="inline-flex items-center gap-1.5"><span className="grid h-[18px] w-[18px] place-items-center rounded-full bg-[#0866ff] text-white"><ThumbsUp className="h-2.5 w-2.5 fill-current" /></span>{post.reactionCount + Number(liked)}</span>
                  <span>{totalComments} {isArabic ? "تعليقات وردود" : "comments and replies"} · {post.shareCount} {isArabic ? "مشاركات" : "shares"}</span>
                </div>
                <div className="grid grid-cols-3 border-t border-[#e4e6eb] px-2 py-1 sm:px-4">
                  <button type="button" aria-pressed={liked} onClick={() => setLikedPosts((previous) => { const next = new Set(previous); if (next.has(post.id)) next.delete(post.id); else next.add(post.id); return next; })} className={cn("flex items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold hover:bg-[#f0f2f5]", liked ? "text-[#0866ff]" : "text-[#65676b]")}><ThumbsUp className={cn("h-4 w-4", liked && "fill-current")} />{isArabic ? "أعجبني" : "Like"}</button>
                  <button type="button" aria-pressed={commentingPost === post.id} onClick={() => { setCommentingPost((current) => current === post.id ? null : post.id); setCommentDraft(""); }} className="flex items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold text-[#65676b] hover:bg-[#f0f2f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]"><MessageCircle className="h-4 w-4" />{isArabic ? "تعليق" : "Comment"}</button>
                  <button type="button" disabled title={isArabic ? "المشاركة غير متاحة في العرض التجريبي" : "Sharing is unavailable in this demo"} className="flex cursor-not-allowed items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold text-[#8a8d91]"><Share2 className="h-4 w-4" />{isArabic ? "مشاركة" : "Share"}</button>
                </div>
              </div>
              <div className="flex shrink-0 items-center justify-between border-b border-[#e4e6eb] bg-[#f7f8fa] px-4 py-2.5 sm:px-5">
                <h4 className="text-[12px] font-bold text-[#1c1e21]">{isArabic ? "التعليقات" : "Comments"}</h4>
                <span className="text-[10.5px] text-[#65676b]">{totalComments}</span>
              </div>
              {commentingPost === post.id && <form onSubmit={(event) => submitPageComment(event, post)} className="flex shrink-0 items-center gap-2 border-b border-[#e4e6eb] px-4 py-2.5 sm:px-5">
                <Avatar src={post.pageAvatarUrl} name={post.pageName} size="h-8 w-8" />
                <div className="flex min-w-0 flex-1 items-center rounded-full bg-[#f0f2f5] px-3 focus-within:ring-2 focus-within:ring-[#0866ff]/40">
                  <input autoFocus value={commentDraft} onChange={(event) => setCommentDraft(event.target.value)} dir={isArabic ? "rtl" : "ltr"} placeholder={isArabic ? "اكتب تعليقًا بصفتك الصفحة..." : "Comment as Page..."} className="min-w-0 flex-1 bg-transparent py-2 text-[12px] outline-none placeholder:text-[#8a8d91]" />
                  <button type="submit" disabled={!commentDraft.trim()} aria-label={isArabic ? "نشر التعليق" : "Post comment"} className="grid h-7 w-7 place-items-center rounded-full text-[#0866ff] hover:bg-white disabled:opacity-40"><Send className="h-4 w-4" /></button>
                </div>
              </form>}
              {commentNotice === post.id && <p role="status" className="shrink-0 border-b border-[#e4e6eb] px-5 py-1 text-[10.5px] text-[#237a57]">{isArabic ? "تمت إضافة تعليق الصفحة محليًا" : "Page comment added locally"}</p>}
              <div className="min-h-0 flex-1 overflow-y-auto bg-white px-4 py-3 sm:px-5 sm:py-4">
                <div className="mx-auto max-w-[900px] space-y-3">
                  {(post.comments || []).map((comment) => <CommentThread key={comment.id} comment={comment} pageName={post.pageName} onReply={onReply} lang={lang} />)}
                  {(post.comments || []).length === 0 && <p className="py-8 text-center text-[12px] text-[#65676b]">{isArabic ? "لا توجد تعليقات بعد." : "No comments yet."}</p>}
                </div>
              </div>
            </>;
          })() : <div className="m-auto max-w-sm px-6 text-center">
            <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-[#e7f3ff] text-[#0866ff]"><Facebook className="h-6 w-6" /></span>
            <h3 className="mt-4 text-[15px] font-semibold text-[#1c1e21]">{posts.length ? (isArabic ? "اختر منشورًا لعرض التعليقات" : "Select a post to view comments") : (isArabic ? "لا تتوفر منشورات لهذه الصفحة" : "No Page posts are available")}</h3>
            <p className="mt-1 text-[12px] leading-5 text-[#65676b]">{isArabic ? "ستظهر هنا تفاصيل المنشور والتعليقات والردود." : "Post details, comments, and replies will appear here."}</p>
          </div>}
        </div>
      </div>
    </section>
  );
}
