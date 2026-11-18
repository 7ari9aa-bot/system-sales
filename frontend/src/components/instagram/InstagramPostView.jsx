import React, { useEffect, useRef, useState } from "react";
import IgAvatar from "./IgAvatar";
import IgComment from "./IgComment";
import { IG } from "./igTheme";
import { IgBack, IgClose, IgComment as CommentIcon, IgEmoji, IgShare } from "./igIcons";
import { cn } from "@/lib/utils";

const EMOJIS = ["😀", "😂", "😍", "🥰", "😎", "🤩", "😢", "😡", "👍", "🙏", "👏", "🔥", "❤️", "💯", "🎉", "✨"];

/** Instagram's post modal: picture on one side, caption, comments and the reply box on the other. */
export default function InstagramPostView({ post, lang = "ar", actions = {}, onClose, onPrev, onNext }) {
  const isArabic = lang === "ar";
  const [replyTo, setReplyTo] = useState(null);
  const [privateFor, setPrivateFor] = useState(null);
  const [draft, setDraft] = useState("");
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target?.tagName === "TEXTAREA") return;
      if (event.key === "Escape") onClose?.();
      if (event.key === "ArrowLeft") (isArabic ? onNext : onPrev)?.();
      if (event.key === "ArrowRight") (isArabic ? onPrev : onNext)?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onPrev, onNext, isArabic]);

  useEffect(() => { setReplyTo(null); setPrivateFor(null); setDraft(""); setActionError(""); }, [post?.id]);

  if (!post) return null;
  const canSend = Boolean(privateFor || replyTo || actions.canComment);
  const focus = () => requestAnimationFrame(() => inputRef.current?.focus());

  async function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending || !canSend) return;
    setSending(true);
    setActionError("");
    try {
      if (privateFor) await actions.sendPrivate?.(privateFor.id, post.id, text);
      else await actions.reply?.(replyTo?.id || null, post.id, text);
      setDraft(""); setReplyTo(null); setPrivateFor(null); setEmojiOpen(false);
    } catch (error) {
      setActionError(error?.message || (isArabic ? "تعذر الإرسال" : "Could not send"));
    } finally {
      setSending(false);
    }
  }
  async function run(fn) {
    setActionError("");
    try { await fn(); } catch (error) { setActionError(error?.message || (isArabic ? "تعذر تنفيذ الإجراء" : "Action failed")); }
  }
  const commentActions = {
    hide: actions.hide && ((c) => run(() => actions.hide(c.id, post.id, !c.hidden))),
    remove: actions.remove && ((c) => run(() => actions.remove(c.id, post.id))),
    privateReply: actions.sendPrivate && ((c) => { setPrivateFor(c); setReplyTo(null); focus(); }),
  };
  const arrow = "absolute top-1/2 z-10 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-white text-black shadow hover:opacity-90";

  return (
    <div role="dialog" aria-modal="true" aria-label={isArabic ? "منشور" : "Post"} className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-0 md:p-10" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <button type="button" onClick={onClose} aria-label={isArabic ? "إغلاق" : "Close"} className="absolute end-4 top-4 hidden text-white md:block"><IgClose size={26} /></button>
      {onPrev && <button type="button" onClick={onPrev} aria-label={isArabic ? "السابق" : "Previous"} className={cn(arrow, "start-4 hidden md:grid")}><IgBack size={16} className={isArabic ? "-scale-x-100" : undefined} /></button>}
      {onNext && <button type="button" onClick={onNext} aria-label={isArabic ? "التالي" : "Next"} className={cn(arrow, "end-4 hidden md:grid")}><IgBack size={16} className={isArabic ? undefined : "-scale-x-100"} /></button>}
      <article dir={isArabic ? "rtl" : "ltr"} data-testid="ig-post-card" className="flex h-full w-full max-w-[1200px] flex-col overflow-hidden bg-white md:h-[min(90vh,800px)] md:flex-row md:rounded-[4px]" style={{ fontFamily: IG.font }}>
        <header className="flex h-11 shrink-0 items-center border-b px-4 md:hidden" style={{ borderColor: IG.separator }}>
          <button type="button" onClick={onClose} aria-label={isArabic ? "رجوع" : "Back"}><IgBack className={isArabic ? "-scale-x-100" : undefined} /></button>
          <h2 className="flex-1 text-center text-[16px] font-semibold">{isArabic ? "منشور" : "Post"}</h2><span className="w-6" />
        </header>
        <div className="flex min-h-[240px] flex-[1.4] items-center justify-center bg-black">
          {post.mediaUrl
            ? post.mediaType === "video"
              ? <video src={post.mediaUrl} controls playsInline className="max-h-full max-w-full" />
              : <img src={post.mediaUrl} alt={isArabic ? "صورة المنشور" : "Post media"} className="max-h-full max-w-full object-contain" />
            : <span className="text-[14px] text-white/70">{isArabic ? "لا توجد صورة" : "No media"}</span>}
        </div>
        <div className="flex min-h-0 w-full flex-1 flex-col md:w-[405px] md:flex-none md:border-s md:max-w-[500px]" style={{ borderColor: IG.separator }}>
          <header className="flex h-[60px] shrink-0 items-center gap-3 border-b px-4" style={{ borderColor: IG.separator }}>
            <IgAvatar src={post.accountAvatarUrl} size={32} ring />
            <p dir="ltr" className="min-w-0 flex-1 truncate text-[14px] font-semibold">{post.accountName || "Instagram"}</p>
          </header>
          <section aria-label={isArabic ? "تعليقات المنشور" : "Post comments"} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
            {post.text && (
              <div className="flex items-start gap-3">
                <IgAvatar src={post.accountAvatarUrl} size={32} />
                <div className="min-w-0 flex-1 text-[14px] leading-[18px]">
                  <bdi dir="ltr" className="me-1 font-semibold">{post.accountName || "Instagram"}</bdi>
                  <span dir="auto" className="whitespace-pre-wrap break-words [unicode-bidi:isolate]">{post.text}</span>
                  <p className="mt-2 text-[12px] leading-4" style={{ color: IG.secondary }}>{post.timeLabel}</p>
                </div>
              </div>
            )}
            {(post.comments || []).length
              ? post.comments.map((comment) => <IgComment key={comment.id} comment={comment} isArabic={isArabic} actions={commentActions} pageAvatar={post.accountAvatarUrl} onReply={() => { setPrivateFor(null); setReplyTo(comment); setDraft((d) => d || `@${comment.handle || comment.author} `); focus(); }} />)
              : <div className="grid min-h-[200px] place-items-center text-center"><div><p className="text-[24px] font-bold">{isArabic ? "لا توجد تعليقات بعد." : "No comments yet."}</p><p className="mt-2 text-[14px]">{isArabic ? "عندما يعلّق أحد ستراه هنا." : "When someone comments, you'll see it here."}</p></div></div>}
          </section>
          <div className="shrink-0 border-t px-4 pb-2 pt-1.5" style={{ borderColor: IG.separator }}>
            <div className="flex items-center gap-4 py-1.5">
              <button type="button" onClick={focus} aria-label={isArabic ? "تعليق" : "Comment"} className="hover:opacity-60"><CommentIcon className={isArabic ? "-scale-x-100" : undefined} /></button>
              {post.permalink
                ? <a href={post.permalink} target="_blank" rel="noreferrer" aria-label={isArabic ? "مشاركة" : "Share"} className="hover:opacity-60"><IgShare /></a>
                : null}
            </div>
            <p className="text-[14px] font-semibold">{Number(post.likes || 0).toLocaleString(isArabic ? "ar-EG" : "en-US")} {isArabic ? "إعجاب" : post.likes === 1 ? "like" : "likes"}</p>
            <p className="mt-1 text-[10px] uppercase tracking-[0.2px]" style={{ color: IG.secondary }}>{post.timeLabel}</p>
          </div>
          {emojiOpen && (
            <div role="group" aria-label={isArabic ? "الرموز التعبيرية" : "Emoji"} data-testid="ig-emoji-panel" className="grid shrink-0 grid-cols-8 gap-1 border-t px-3 py-2 text-[22px]" style={{ borderColor: IG.separator }}>
              {EMOJIS.map((emoji) => <button key={emoji} type="button" onClick={() => { setDraft((d) => d + emoji); focus(); }} className="grid h-9 place-items-center rounded hover:bg-[#f2f2f2]">{emoji}</button>)}
            </div>
          )}
          {canSend && <form onSubmit={submit} className="shrink-0 border-t px-4 py-2" style={{ borderColor: IG.separator }}>
            {actionError && <div role="alert" data-testid="ig-action-error" className="mb-2 text-[12px]" style={{ color: IG.error }}>{actionError}</div>}
            {privateFor && <div data-testid="ig-private-banner" className="mb-2 flex items-center justify-between text-[12px]" style={{ color: IG.secondary }}><span>{isArabic ? <>رسالة خاصة إلى <b className="text-black">{privateFor.handle || privateFor.author}</b> (مرة واحدة فقط)</> : <>Private message to <b className="text-black">{privateFor.handle || privateFor.author}</b> (one time only)</>}</span><button type="button" onClick={() => setPrivateFor(null)} className="font-semibold text-black">{isArabic ? "إلغاء" : "Cancel"}</button></div>}
            {replyTo && !privateFor && <div className="mb-2 flex items-center justify-between text-[12px]" style={{ color: IG.secondary }}><span>{isArabic ? <>الرد على <b className="text-black">{replyTo.handle || replyTo.author}</b></> : <>Replying to <b className="text-black">{replyTo.handle || replyTo.author}</b></>}</span><button type="button" onClick={() => { setReplyTo(null); setDraft(""); }} className="font-semibold text-black">{isArabic ? "إلغاء" : "Cancel"}</button></div>}
            <div className="flex min-h-10 items-center gap-3">
              <button type="button" onClick={() => setEmojiOpen((v) => !v)} aria-label={isArabic ? "الرموز التعبيرية" : "Emoji"} aria-expanded={emojiOpen} className="shrink-0 hover:opacity-60 disabled:opacity-30"><IgEmoji size={24} /></button>
              <textarea id="instagram-comment-reply" ref={inputRef} rows={1} value={draft} onChange={(event) => setDraft(event.target.value)} 
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}
                dir="auto" placeholder={privateFor ? (isArabic ? "اكتب رسالتك..." : "Write a message...") : (isArabic ? "أضف تعليقًا..." : "Add a comment...")}
                className="max-h-20 min-w-0 flex-1 resize-none bg-transparent py-2 text-[14px] outline-none placeholder:text-[#737373]" />
              <button type="submit" disabled={!draft.trim() || sending} className="shrink-0 text-[14px] font-semibold hover:text-[#00376b] disabled:opacity-30" style={{ color: IG.blue }}>{privateFor ? (isArabic ? "إرسال" : "Send") : (isArabic ? "نشر" : "Post")}</button>
            </div>
          </form>}
        </div>
      </article>
    </div>
  );
}
