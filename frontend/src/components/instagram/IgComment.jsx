import React, { useState } from "react";
import IgAvatar from "./IgAvatar";
import { IgHeart, IgMore } from "./igIcons";
import { cn } from "@/lib/utils";

const PRIVATE_REPLY_MS = 7 * 24 * 3600 * 1000;

/** One comment as Instagram draws it, plus the shop's moderation actions in its ••• menu. */
export default function IgComment({ comment, isArabic, onReply, actions, pageAvatar, nested = false }) {
  const [showReplies, setShowReplies] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const age = comment.commentedAt ? Date.now() - new Date(comment.commentedAt).getTime() : 0;
  const canPrivate = !comment.isPage && !comment.privateRepliedAt && age <= PRIVATE_REPLY_MS;
  const privateTitle = comment.privateRepliedAt
    ? (isArabic ? "تم إرسال رد خاص لهذا التعليق" : "Private reply already sent")
    : age > PRIVATE_REPLY_MS ? (isArabic ? "انتهت مهلة الرد الخاص (7 أيام)" : "Private reply window (7 days) has passed") : "";
  const replies = comment.replies || [];
  const hasMenu = (actions?.hide && !comment.isPage) || actions?.remove || (actions?.privateReply && !comment.isPage);
  return (
    <div data-testid="ig-comment" data-hidden={comment.hidden ? "true" : "false"} className={cn("group", nested && "ms-[44px]")}>
      <div className={cn("flex items-start gap-3", comment.hidden && "opacity-55")}>
        <IgAvatar src={comment.isPage ? pageAvatar : comment.avatarUrl} size={32} />
        <div className="min-w-0 flex-1">
          <div className="text-[14px] leading-[18px]">
            <bdi dir="auto" className="me-1 font-semibold">{comment.handle || comment.author}</bdi>
            <span dir="auto" className="whitespace-pre-wrap break-words [unicode-bidi:isolate]">{comment.text}</span>
            {comment.isAgent && <span className="ms-1.5 text-[11px] font-semibold text-[#737373]">· {isArabic ? "رد تلقائي" : "Auto reply"}</span>}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] font-semibold leading-4 text-[#737373]">
            <span className="font-normal">{comment.timeLabel}</span>
            {comment.likes > 0 && <span>{comment.likes} {isArabic ? "إعجاب" : comment.likes === 1 ? "like" : "likes"}</span>}
            <button type="button" onClick={onReply} className="hover:text-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6]">{isArabic ? "رد" : "Reply"}</button>
            {comment.isPage && !comment.isAgent && <span className="font-normal">{isArabic ? "أنت" : "You"}</span>}
            {comment.hidden && <span data-testid="ig-hidden-badge" className="font-normal">{isArabic ? "مخفي" : "Hidden"}</span>}
            {hasMenu && (
              <span className="relative">
                <button type="button" aria-label={isArabic ? "خيارات التعليق" : "Comment options"} aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)} className="grid place-items-center opacity-100 hover:text-black md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100 md:aria-expanded:opacity-100"><IgMore size={16} /></button>
              </span>
            )}
          </div>
          {menuOpen && hasMenu && (
            <div role="menu" className="mt-2 flex flex-wrap gap-2 text-[12px] font-semibold">
              {actions?.privateReply && !comment.isPage && <button type="button" role="menuitem" data-testid="ig-private-reply" disabled={!canPrivate} title={privateTitle} onClick={() => { setMenuOpen(false); actions.privateReply(comment); }} className="rounded-lg bg-[#efefef] px-3 py-1.5 hover:bg-[#dbdbdb] disabled:cursor-not-allowed disabled:opacity-40">{isArabic ? "رد خاص" : "Private reply"}</button>}
              {actions?.hide && !comment.isPage && <button type="button" role="menuitem" data-testid="ig-hide" onClick={() => { setMenuOpen(false); actions.hide(comment); }} className="rounded-lg bg-[#efefef] px-3 py-1.5 hover:bg-[#dbdbdb]">{comment.hidden ? (isArabic ? "إظهار" : "Unhide") : (isArabic ? "إخفاء" : "Hide")}</button>}
              {actions?.remove && <button type="button" role="menuitem" data-testid="ig-delete" onClick={() => { setMenuOpen(false); if (window.confirm(isArabic ? "حذف التعليق نهائيًا من إنستغرام؟" : "Delete this comment from Instagram for good?")) actions.remove(comment); }} className="rounded-lg bg-[#efefef] px-3 py-1.5 text-[#ed4956] hover:bg-[#dbdbdb]">{isArabic ? "حذف" : "Delete"}</button>}
            </div>
          )}
        </div>
        <span className="mt-1 shrink-0 text-[#737373]" title={isArabic ? "الإعجاب بالتعليقات غير متاح عبر واجهة إنستغرام" : "Liking comments isn't available through Instagram's API"}><IgHeart size={12} /></span>
      </div>
      {replies.length > 0 && (
        <div className="ms-[44px] mt-4">
          <button type="button" onClick={() => setShowReplies((v) => !v)} className="flex items-center gap-4 text-[12px] font-semibold text-[#737373]">
            <span className="h-px w-6 bg-[#737373]" />
            {showReplies ? (isArabic ? "إخفاء الردود" : "Hide replies") : (isArabic ? `عرض الردود (${replies.length})` : `View replies (${replies.length})`)}
          </button>
          {showReplies && <div className="mt-4 space-y-4">{replies.map((reply) => <IgComment key={reply.id} comment={reply} isArabic={isArabic} onReply={onReply} actions={actions} pageAvatar={pageAvatar} nested={false} />)}</div>}
        </div>
      )}
    </div>
  );
}
