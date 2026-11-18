import React, { useState } from "react";
import IgAvatar from "./IgAvatar";
import { IgMore } from "./igIcons";
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
          <div className="flex items-baseline gap-2 text-[14px] leading-[18px]">
            <bdi dir="auto" className="font-semibold">{comment.handle || comment.author}</bdi>
            <span className="font-normal text-[#6a717a]">{comment.timeLabel}</span>
            {comment.isAgent && <span className="text-[12px] font-semibold text-[#6a717a]">· {isArabic ? "رد تلقائي" : "Auto reply"}</span>}
          </div>
          <div dir="auto" className="whitespace-pre-wrap break-words text-[14px] leading-[18px] [unicode-bidi:isolate]">{comment.text}</div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[12px] font-semibold leading-4 text-[#6a717a]">
            {comment.likes > 0 && <span>{comment.likes} {isArabic ? "إعجاب" : comment.likes === 1 ? "like" : "likes"}</span>}
            <button type="button" onClick={onReply} className="hover:text-[#0c1014] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6]">{isArabic ? "رد" : "Reply"}</button>
            {comment.isPage && !comment.isAgent && <span className="font-normal">{isArabic ? "أنت" : "You"}</span>}
            {comment.hidden && <span data-testid="ig-hidden-badge" className="font-normal">{isArabic ? "مخفي" : "Hidden"}</span>}
            {hasMenu && (
              <span className="relative">
                <button type="button" aria-label={isArabic ? "خيارات التعليق" : "Comment options"} aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)} className="grid place-items-center opacity-100 hover:text-[#0c1014] md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100 md:aria-expanded:opacity-100"><IgMore size={16} /></button>
              </span>
            )}
          </div>
          {menuOpen && hasMenu && (
            <div role="menu" className="mt-2 flex flex-wrap gap-2 text-[12px] font-semibold">
              {actions?.privateReply && !comment.isPage && <button type="button" role="menuitem" data-testid="ig-private-reply" disabled={!canPrivate} title={privateTitle} onClick={() => { setMenuOpen(false); actions.privateReply(comment); }} className="rounded-lg bg-[#f3f5f7] px-3 py-1.5 hover:bg-[#dbdfe4] disabled:cursor-not-allowed disabled:opacity-40">{isArabic ? "رد خاص" : "Private reply"}</button>}
              {actions?.hide && !comment.isPage && <button type="button" role="menuitem" data-testid="ig-hide" onClick={() => { setMenuOpen(false); actions.hide(comment); }} className="rounded-lg bg-[#f3f5f7] px-3 py-1.5 hover:bg-[#dbdfe4]">{comment.hidden ? (isArabic ? "إظهار" : "Unhide") : (isArabic ? "إخفاء" : "Hide")}</button>}
              {actions?.remove && <button type="button" role="menuitem" data-testid="ig-delete" onClick={() => { setMenuOpen(false); if (window.confirm(isArabic ? "حذف التعليق نهائيًا من إنستغرام؟" : "Delete this comment from Instagram for good?")) actions.remove(comment); }} className="rounded-lg bg-[#f3f5f7] px-3 py-1.5 text-[#ed4956] hover:bg-[#dbdfe4]">{isArabic ? "حذف" : "Delete"}</button>}
            </div>
          )}
        </div>
      </div>
      {replies.length > 0 && (
        <div className="ms-[44px] mt-4">
          <button type="button" onClick={() => setShowReplies((v) => !v)} className="flex items-center gap-4 text-[12px] font-semibold text-[#6a717a]">
            <span className="h-px w-6 bg-[#6a717a]" />
            {showReplies ? (isArabic ? "إخفاء الردود" : "Hide replies") : (isArabic ? `عرض الردود (${replies.length})` : `View replies (${replies.length})`)}
          </button>
          {showReplies && <div className="mt-4 space-y-4">{replies.map((reply) => <IgComment key={reply.id} comment={reply} isArabic={isArabic} onReply={onReply} actions={actions} pageAvatar={pageAvatar} nested={false} />)}</div>}
        </div>
      )}
    </div>
  );
}
