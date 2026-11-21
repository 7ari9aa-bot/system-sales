import React, { useState } from "react";
import FbAvatar from "@/components/facebook/FbAvatar";
import FbComment from "@/components/facebook/FbComment";
import { FB } from "@/components/facebook/fbTheme";
import FbReactionSummary from "@/components/facebook/FbReactionSummary";
import { FbComment as CommentIcon, FbGlobe, FbLike } from "@/components/facebook/fbIcons";
import { commentWindow } from "@/lib/facebookApi";
import { cn } from "@/lib/utils";

const countAll = (comments) => (comments || []).reduce((n, c) => n + 1 + (c.replies || []).length, 0);

/** Facebook only draws the Post button in a comment box once there is something to post; an empty
 *  box is just the placeholder and the picture icons. */
export const commentSubmitShown = (draft) => String(draft || "").trim().length > 0;

/** What a screen reader hears on the Comment action: Facebook puts the thread's count on that button,
 *  so the count belongs in its name too ("Comment, 3 comments"). */
export function commentActionLabel(count, lang) {
  const ar = lang === "ar";
  if (!(count > 0)) return ar ? "تعليق" : "Comment";
  if (ar) return `تعليق، ${count === 1 ? "تعليق واحد" : `${count} تعليقات`}`;
  return `Comment, ${count} ${count === 1 ? "comment" : "comments"}`;
}

/** A Page post as Facebook draws it: header, text, picture, counts, Like / Comment, then the comments. */
export default function FbPostCard({ post, pageName, pageAvatar, lang, actions, onEdited, onDeleted, onOpenInsights }) {
  const ar = lang === "ar";
  const [liked, setLiked] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(post.text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState(false);
  const [steps, setSteps] = useState(0);
  const total = Math.max(post.commentsCount || 0, countAll(post.comments));
  const win = commentWindow(post.comments, steps);

  const run = async (fn, after) => {
    setBusy(true);
    setError("");
    try { await fn(); after?.(); } catch (e) { setError(e?.message || (ar ? "تعذّر التنفيذ" : "That did not go through")); } finally { setBusy(false); }
  };
  const like = () => run(async () => { await actions.like(post.id, !liked); setLiked((v) => !v); });
  const sendComment = (event) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value || busy) return;
    run(() => actions.comment(post.id, value), () => { setDraft(""); });
  };
  const saveEdit = (event) => {
    event.preventDefault();
    if (!text.trim() || busy) return;
    run(() => actions.edit(post.id, text), () => { setEditing(false); onEdited?.(); });
  };
  const remove = () => {
    setMenu(false);
    if (window.confirm(ar ? "حذف هذا المنشور من الصفحة نهائيًا؟" : "Delete this post from the Page for good?")) run(() => actions.removePost(post.id), onDeleted);
  };
  const item = "flex w-full items-center gap-2 rounded-md px-3 py-2 text-start text-[15px] font-semibold hover:bg-[#f2f2f2]";
  const reactionsShown = post.reactions + (liked ? 1 : 0);
  return (
    <article className="rounded-lg bg-white shadow-[0_1px_2px_rgba(0,0,0,0.2)]" aria-label={ar ? "منشور" : "Post"}>
      <header className="flex items-start gap-2 px-4 pt-3">
        <FbAvatar src={pageAvatar} name={pageName} size="h-10 w-10" />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[15px] font-semibold leading-tight">{pageName}</h3>
          <p className="flex items-center gap-1 text-[13px]" style={{ color: FB.text2 }}>
            {post.permalink ? <a href={post.permalink} target="_blank" rel="noreferrer noopener" className="hover:underline">{post.timeLabel}</a> : post.timeLabel}
            <span aria-hidden="true">·</span><FbGlobe size={12} />
          </p>
        </div>
        <div className="relative">
          <button type="button" onClick={() => setMenu((v) => !v)} aria-haspopup="menu" aria-expanded={menu} aria-label={ar ? "خيارات المنشور" : "Post options"} className="grid h-9 w-9 place-items-center rounded-full text-[#65676b] hover:bg-[#f2f2f2]"><span className="text-[20px] leading-none">⋯</span></button>
          {menu && (
            <div role="menu" className="absolute end-0 top-10 z-20 w-56 rounded-lg bg-white p-1.5 shadow-[0_12px_28px_rgba(0,0,0,0.2),0_2px_4px_rgba(0,0,0,0.1)]">
              <button role="menuitem" type="button" className={item} onClick={() => { setMenu(false); setEditing(true); setText(post.text); }}>{ar ? "تعديل المنشور" : "Edit post"}</button>
              <button role="menuitem" type="button" className={item} onClick={() => { setMenu(false); onOpenInsights?.(post); }}>{ar ? "عرض الإحصاءات" : "View insights"}</button>
              <button role="menuitem" type="button" className={cn(item, "text-[#e41e3f]")} onClick={remove}>{ar ? "حذف المنشور" : "Delete post"}</button>
            </div>
          )}
        </div>
      </header>
      {editing ? (
        <form onSubmit={saveEdit} className="px-4 py-3">
          <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={4} dir="auto" aria-label={ar ? "نص المنشور" : "Post text"} className="w-full resize-none rounded-lg border p-3 text-[15px] outline-none focus:border-[#0866ff]" style={{ borderColor: FB.border }} />
          <p className="mt-1 text-[12px]" style={{ color: FB.text2 }}>{ar ? "فيسبوك يسمح بتعديل المنشورات التي نُشرت من هذا التطبيق فقط." : "Facebook only lets an app edit posts that app published."}</p>
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={() => setEditing(false)} className="rounded-md px-4 py-1.5 text-[15px] font-semibold hover:bg-[#f2f2f2]">{ar ? "إلغاء" : "Cancel"}</button>
            <button type="submit" disabled={!text.trim() || busy} className="rounded-md px-4 py-1.5 text-[15px] font-semibold text-white disabled:bg-[#e4e6eb] disabled:text-[#bcc0c4]" style={{ background: FB.blue }}>{ar ? "حفظ" : "Save"}</button>
          </div>
        </form>
      ) : post.text ? <p dir="auto" className="whitespace-pre-wrap break-words px-4 pb-3 pt-2 text-[15px] leading-[1.33]">{post.text}</p> : <div className="h-2" />}
      {post.picture && <img src={post.picture} alt="" loading="lazy" className="max-h-[560px] w-full bg-[#f2f4f7] object-cover" />}
      {reactionsShown > 0 && (
        <div className="flex items-center justify-between px-4 py-2.5 text-[15px]" style={{ color: FB.text2 }}>
          <FbReactionSummary objectId={post.id} total={reactionsShown} lang={lang} />
        </div>
      )}
      <div className="mx-4 grid grid-cols-2 border-y py-1" style={{ borderColor: FB.divider }}>
        <button type="button" aria-pressed={liked} disabled={busy} onClick={like} className={cn("flex h-9 items-center justify-center gap-2 rounded-md text-[15px] font-semibold hover:bg-[#f2f2f2] disabled:opacity-60", liked ? "text-[#0866ff]" : "text-[#65676b]")}><FbLike filled={liked} size={20} />{ar ? "أعجبني" : "Like"}</button>
        <button type="button" data-testid="fb-comment-action" aria-pressed={commenting} aria-label={commentActionLabel(total, lang)} onClick={() => setCommenting((v) => !v)} className="flex h-9 items-center justify-center gap-2 rounded-md text-[15px] font-semibold text-[#65676b] hover:bg-[#f2f2f2]"><CommentIcon size={20} />{ar ? "تعليق" : "Comment"}{total > 0 && <span data-testid="fb-comment-count" aria-hidden="true">{total}</span>}</button>
      </div>
      {error && <p role="alert" className="px-4 pt-2 text-[13px]" style={{ color: FB.red }}>{error}</p>}
      <div className="space-y-3 px-4 py-3">
        {win.hidden > 0 && (
          <button type="button" onClick={() => setSteps((n) => n + 1)} className="block text-[15px] font-semibold hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]" style={{ color: FB.text2 }}>
            {ar ? `عرض ${win.next} تعليقات أخرى` : `View ${win.next} more ${win.next === 1 ? "comment" : "comments"}`}
          </button>
        )}
        {win.shown.map((c) => <FbComment key={c.id} comment={c} postId={post.id} pageName={pageName} pageAvatar={pageAvatar} lang={lang} actions={actions} />)}
        {(post.comments || []).length === 0 && (
          <div className="py-4 text-center" style={{ color: FB.text2 }}>
            <p className="text-[17px] font-bold">{ar ? "لا توجد تعليقات حتى الآن" : "No comments yet"}</p>
            <p className="text-[15px]">{ar ? "كن أول من يعلّق" : "Be the first to comment"}</p>
          </div>
        )}
        <form onSubmit={sendComment} className="flex items-center gap-2">
          <FbAvatar src={pageAvatar} name={pageName} size="h-8 w-8" />
          <div className="flex min-w-0 flex-1 items-center rounded-full px-3" style={{ background: FB.bubble }}>
            <input autoFocus={commenting} value={draft} onChange={(e) => setDraft(e.target.value)} disabled={busy} dir="auto" aria-label={ar ? "اكتب تعليقًا" : "Write a comment"} placeholder={ar ? `التعليق باسم ${pageName}...` : `Comment as ${pageName}...`} className="min-w-0 flex-1 bg-transparent py-2 text-[15px] outline-none placeholder:text-[#65676b]" />
            {commentSubmitShown(draft) && (
              <button type="submit" data-testid="fb-comment-submit" disabled={busy} className="px-1 text-[14px] font-semibold text-[#0866ff] disabled:text-[#bcc0c4]">{ar ? "نشر" : "Post"}</button>
            )}
          </div>
        </form>
      </div>
    </article>
  );
}
