import React, { useState } from "react";
import FbAvatar from "@/components/facebook/FbAvatar";
import { FB } from "@/components/facebook/fbTheme";
import { mentionHandle, replyMention } from "@/lib/facebookApi";
import { cn } from "@/lib/utils";

// Meta allows one private reply per comment, within 7 days of it (can_reply_privately).
const PRIVATE_REPLY_DAYS = 7;
export const canPrivateReply = (comment, now = Date.now()) => {
  const at = new Date(comment.commentedAt || 0).getTime();
  return Number.isFinite(at) && at > 0 && now - at <= PRIVATE_REPLY_DAYS * 86400000;
};

/** What sits on a comment's name line, in order: the name, the Author badge on a Page's own comment,
 *  then the age. Facebook keeps the age up there beside the name, not under the bubble. */
export function commentHeader(comment, lang) {
  const ar = lang === "ar";
  const parts = [{ kind: "author", text: comment.author }];
  if (comment.isPage) parts.push({ kind: "badge", text: ar ? "كاتب المنشور" : "Author" });
  if (comment.timeLabel) parts.push({ kind: "time", text: comment.timeLabel });
  return parts;
}

/** One comment like Facebook draws it: grey bubble with name, badge and age, then Like · Reply. Every action goes to Facebook first. */
export default function FbComment({ comment, postId, pageName, pageAvatar, lang, actions, depth = 0 }) {
  const ar = lang === "ar";
  const [replying, setReplying] = useState(false);
  const [privateOpen, setPrivateOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [liked, setLiked] = useState(false);
  const [tagged, setTagged] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async (fn, after) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      after?.();
    } catch (e) {
      setError(e?.message || (ar ? "تعذّر التنفيذ" : "That did not go through"));
    } finally {
      setBusy(false);
    }
  };
  const submit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    // Facebook opens a reply with the person's name already in it; a public reply tags them unless
    // the owner removed the name. A private reply goes to one person's inbox, so it tags nobody.
    const send = privateOpen ? actions.sendPrivate(comment.id, postId, text) : actions.reply(comment.id, postId, text, replyMention(comment, { tagged, privateReply: privateOpen }));
    run(() => send, () => { setDraft(""); setReplying(false); setPrivateOpen(false); setTagged(true); });
  };
  const toggleLike = () => run(async () => { await actions.like(comment.id, !liked); setLiked((v) => !v); });
  const link = "font-semibold hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff] disabled:opacity-50";
  const shownLikes = (comment.likes || 0) + (liked ? 1 : 0);
  return (
    <div className={cn("min-w-0", comment.hidden && "opacity-60")}>
      <div className="flex items-start gap-2">
        <FbAvatar src={comment.isPage ? pageAvatar : ""} name={comment.author} size={depth ? "h-7 w-7" : "h-8 w-8"} />
        <div className="min-w-0 flex-1">
          <div className="relative inline-block max-w-full rounded-[18px] px-3 py-2 text-[15px] leading-[1.35]" style={{ background: FB.bubble }}>
            <span className="flex flex-wrap items-baseline gap-x-1.5">
              {commentHeader(comment, lang).map((part) => (
                part.kind === "author" ? <span key="author" className="text-[13px] font-semibold">{part.text}</span>
                  : part.kind === "badge" ? <span key="badge" className="text-[12px] font-normal" style={{ color: FB.text2 }}>{part.text}</span>
                    : <time key="time" className="text-[12px] font-normal" style={{ color: FB.text2 }}>{part.text}</time>
              ))}
            </span>
            <p dir="auto" className="whitespace-pre-wrap break-words">{comment.text}</p>
            {shownLikes > 0 && <span className="absolute -bottom-2.5 end-1 inline-flex items-center gap-0.5 rounded-full bg-white px-1 py-px text-[12px] shadow-[0_1px_2px_rgba(0,0,0,0.3)]" style={{ color: FB.text2 }}><span className="grid h-4 w-4 place-items-center rounded-full text-[9px] text-white" style={{ background: FB.blue }}>👍</span>{shownLikes}</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 text-[12px]" style={{ color: FB.text2 }}>
            {!comment.isPage && <button type="button" aria-pressed={liked} disabled={busy} onClick={toggleLike} className={cn(link, liked && "text-[#0866ff]")}>{ar ? "أعجبني" : "Like"}</button>}
            {!comment.isPage && !comment.hidden && depth === 0 && <button type="button" onClick={() => { setReplying((v) => !v); setPrivateOpen(false); setTagged(true); }} className={link}>{ar ? "رد" : "Reply"}</button>}
            {comment.hidden && <span className="font-normal">{ar ? "مخفي" : "Hidden"}</span>}
            {!comment.isPage && (
              <button type="button" disabled={busy} onClick={() => run(() => actions.hide(comment.id, postId, !comment.hidden))} className={link}>{comment.hidden ? (ar ? "إظهار" : "Unhide") : (ar ? "إخفاء" : "Hide")}</button>
            )}
            {!comment.isPage && !comment.hidden && !comment.privateRepliedAt && canPrivateReply(comment) && (
              <button type="button" onClick={() => { setPrivateOpen(true); setReplying(true); }} className={link}>{ar ? "رد خاص" : "Message privately"}</button>
            )}
            <button type="button" disabled={busy} onClick={() => { if (window.confirm(ar ? "حذف هذا التعليق نهائيًا؟" : "Delete this comment for good?")) run(() => actions.removeComment(comment.id, postId)); }} className={cn(link, "hover:text-[#e41e3f]")}>{ar ? "حذف" : "Delete"}</button>
          </div>
          {error && <p role="alert" className="mt-1 px-3 text-[12px]" style={{ color: FB.red }}>{error}</p>}
        </div>
      </div>
      {(comment.replies || []).length > 0 && (
        <div className="mt-2 space-y-2 ps-10">
          {comment.replies.map((r) => <FbComment key={r.id} comment={r} postId={postId} pageName={pageName} pageAvatar={pageAvatar} lang={lang} actions={actions} depth={1} />)}
        </div>
      )}
      {replying && (
        <form onSubmit={submit} className="mt-2 flex items-center gap-2 ps-10">
          <FbAvatar src={pageAvatar} name={pageName} size="h-7 w-7" />
          <div className="flex min-w-0 flex-1 items-center gap-1 rounded-full px-3" style={{ background: FB.bubble }}>
            {!privateOpen && tagged && mentionHandle(comment) && (
              <span data-testid="fb-mention-chip" className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#e7f3ff] px-1.5 py-0.5 text-[14px] font-medium text-[#0866ff]">
                {mentionHandle(comment).label}
                <button type="button" onClick={() => setTagged(false)} aria-label={ar ? "إزالة الإشارة" : "Remove mention"} className="leading-none hover:text-[#0b57d0]">×</button>
              </span>
            )}
            <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} dir="auto" disabled={busy} aria-label={privateOpen ? (ar ? "رد خاص" : "Private reply") : (ar ? "رد" : "Reply")} placeholder={privateOpen ? (ar ? "رسالة خاصة للمعلّق في ماسنجر..." : "Private message in Messenger...") : (ar ? `الرد باسم ${pageName}...` : `Reply as ${pageName}...`)} className="min-w-0 flex-1 bg-transparent py-2 text-[15px] outline-none placeholder:text-[#65676b]" />
            <button type="submit" disabled={!draft.trim() || busy} aria-label={ar ? "إرسال" : "Send"} className="px-1 text-[14px] font-semibold text-[#0866ff] disabled:text-[#bcc0c4]">{ar ? "إرسال" : "Send"}</button>
          </div>
        </form>
      )}
    </div>
  );
}
