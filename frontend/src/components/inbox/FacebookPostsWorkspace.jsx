import React, { useState } from "react";
import { Facebook, Globe2, MessageCircle, MoreHorizontal, Send, Share2, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/utils";

function Avatar({ src, name, size = "h-9 w-9" }) {
  const [failed, setFailed] = useState(false);
  const initials = String(name || "F").trim().slice(0, 1);
  return src && !failed
    ? <img src={src} alt="" className={cn(size, "shrink-0 rounded-full object-cover")} onError={() => setFailed(true)} />
    : <span className={cn(size, "grid shrink-0 place-items-center rounded-full bg-[#e7f3ff] text-sm font-semibold text-[#0866ff]")}>{initials}</span>;
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
          {renderBubble(comment.author, comment.text)}
          {renderActions(comment.timeLabel, comment.likes || 0, true)}
        </div>
      </div>
      {(comment.replies || []).length > 0 && (
        <div className="mt-1.5 space-y-2 ps-8 sm:ps-10">
          {comment.replies.map((reply) => (
            <div key={reply.id} className="flex items-start gap-2">
              <Avatar src={reply.avatarUrl || (reply.isPage ? "/fihrist-mark.svg" : undefined)} name={reply.author} size="h-7 w-7" />
              <div className="min-w-0 flex-1">
                {renderBubble(reply.author, reply.text, reply.isPage)}
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
  const [likedPosts, setLikedPosts] = useState(() => new Set());
  const [commentingPost, setCommentingPost] = useState(null);
  const [commentDraft, setCommentDraft] = useState("");
  const [commentNotice, setCommentNotice] = useState("");
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
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 sm:px-6 sm:py-4">
        <div className="mx-auto flex max-w-[850px] flex-col gap-3 sm:gap-4">
          {posts.length === 0 ? (
            <div className="rounded-xl border border-[#d8dadf] bg-white p-8 text-center text-[13px] text-[#65676b]">{isArabic ? "لا تتوفر منشورات لهذه الصفحة." : "No Page posts are available."}</div>
          ) : posts.map((post) => {
            const liked = likedPosts.has(post.id);
            const totalComments = (post.comments || []).reduce((sum, comment) => sum + 1 + (comment.replies || []).length, 0);
            return (
              <article key={post.id} className="overflow-hidden rounded-xl border border-[#d8dadf] bg-white shadow-[0_1px_2px_rgba(0,0,0,.06)]">
                <header className="flex items-center gap-2.5 px-4 pb-2 pt-3.5 sm:px-5">
                  <Avatar src={post.pageAvatarUrl} name={post.pageName} size="h-10 w-10" />
                  <div className="min-w-0 flex-1"><h3 className="truncate text-[13px] font-bold text-[#1c1e21]">{post.pageName}</h3><p className="mt-0.5 flex items-center gap-1 text-[10.5px] text-[#65676b]"><span>{post.timeLabel}</span><span aria-hidden="true">·</span><Globe2 className="h-3 w-3" /></p></div>
                  <button type="button" disabled aria-label={isArabic ? "المزيد غير متاح في العرض التجريبي" : "More options unavailable in this demo"} title={isArabic ? "الخيارات الإضافية غير متاحة في العرض التجريبي" : "More options are unavailable in this demo"} className="grid h-8 w-8 cursor-not-allowed place-items-center rounded-full text-[#8a8d91]"><MoreHorizontal className="h-5 w-5" /></button>
                </header>
                <p dir="auto" className="whitespace-pre-wrap px-4 pb-3 text-[13px] leading-[1.7] text-[#1c1e21] sm:px-5">{post.text}</p>
                {post.mediaUrl && <img src={post.mediaUrl} alt={isArabic ? "صورة من منشور الصفحة" : "Page post image"} className="max-h-[390px] w-full bg-[#f0f2f5] object-cover" loading="lazy" />}
                <div className="flex items-center justify-between border-b border-[#e4e6eb] px-4 py-2 text-[11px] text-[#65676b] sm:px-5">
                  <span className="inline-flex items-center gap-1.5"><span className="grid h-[18px] w-[18px] place-items-center rounded-full bg-[#0866ff] text-white"><ThumbsUp className="h-2.5 w-2.5 fill-current" /></span>{post.reactionCount + Number(liked)}</span>
                  <span>{totalComments} {isArabic ? "تعليقات وردود" : "comments and replies"} · {post.shareCount} {isArabic ? "مشاركات" : "shares"}</span>
                </div>
                <div className="grid grid-cols-3 border-b border-[#e4e6eb] px-2 py-1 sm:px-4">
                  <button type="button" aria-pressed={liked} onClick={() => setLikedPosts((previous) => { const next = new Set(previous); if (next.has(post.id)) next.delete(post.id); else next.add(post.id); return next; })} className={cn("flex items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold hover:bg-[#f0f2f5]", liked ? "text-[#0866ff]" : "text-[#65676b]")}><ThumbsUp className={cn("h-4 w-4", liked && "fill-current")} />{isArabic ? "أعجبني" : "Like"}</button>
                  <button type="button" aria-pressed={commentingPost === post.id} onClick={() => { setCommentingPost((current) => current === post.id ? null : post.id); setCommentDraft(""); }} className="flex items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold text-[#65676b] hover:bg-[#f0f2f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]"><MessageCircle className="h-4 w-4" />{isArabic ? "تعليق" : "Comment"}</button>
                  <button type="button" disabled title={isArabic ? "المشاركة غير متاحة في العرض التجريبي" : "Sharing is unavailable in this demo"} className="flex cursor-not-allowed items-center justify-center gap-1.5 rounded-md py-2 text-[12px] font-semibold text-[#8a8d91]"><Share2 className="h-4 w-4" />{isArabic ? "مشاركة · غير متاحة" : "Share · unavailable"}</button>
                </div>
                {commentingPost === post.id && (
                  <form onSubmit={(event) => submitPageComment(event, post)} className="flex items-center gap-2 border-b border-[#e4e6eb] px-4 py-3 sm:px-5">
                    <Avatar src={post.pageAvatarUrl} name={post.pageName} size="h-8 w-8" />
                    <div className="flex min-w-0 flex-1 items-center rounded-full bg-[#f0f2f5] px-3 focus-within:ring-2 focus-within:ring-[#0866ff]/40">
                      <input autoFocus value={commentDraft} onChange={(event) => setCommentDraft(event.target.value)} dir={isArabic ? "rtl" : "ltr"} placeholder={isArabic ? "اكتب تعليقًا بصفتك الصفحة..." : "Comment as Page..."} className="min-w-0 flex-1 bg-transparent py-2.5 text-[12px] outline-none placeholder:text-[#8a8d91]" />
                      <button type="submit" disabled={!commentDraft.trim()} aria-label={isArabic ? "نشر التعليق" : "Post comment"} className="grid h-7 w-7 place-items-center rounded-full text-[#0866ff] hover:bg-white disabled:opacity-40"><Send className="h-4 w-4" /></button>
                    </div>
                  </form>
                )}
                {commentNotice === post.id && <p role="status" className="border-b border-[#e4e6eb] px-5 py-1 text-[10.5px] text-[#237a57]">{isArabic ? "تمت إضافة تعليق الصفحة محليًا" : "Page comment added locally"}</p>}
                <div className="space-y-3 px-4 py-3 sm:px-5 sm:py-4">
                  {(post.comments || []).map((comment) => <CommentThread key={comment.id} comment={comment} pageName={post.pageName} onReply={onReply} lang={lang} />)}
                  {(post.comments || []).length === 0 && <p className="text-[12px] text-[#65676b]">{isArabic ? "لا توجد تعليقات بعد." : "No comments yet."}</p>}
                </div>
              </article>
            );
          })}
          <p className="pb-2 text-center text-[10.5px] text-[#65676b]">{isArabic ? "بيانات تجريبية محفوظة محليًا لهذا الحساب" : "Demo content stored locally for this account"}</p>
        </div>
      </div>
    </section>
  );
}
