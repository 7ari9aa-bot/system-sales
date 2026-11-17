import React, { useState } from "react";
import ChatListMenu from "./ChatListMenu";
import MessageStatus from "./MessageStatus";
import { CameraIcon, ChevronDownIcon, FileIcon, MicIcon, MuteIcon, PushPinIcon } from "./icons";
import { badgeCount, isMuted, isUnread, listTimestamp } from "./chatListState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: { unread: "غير مقروءة", options: "خيارات المحادثة", pinned: "محادثة مثبتة", muted: "الإشعارات مكتومة", markedUnread: "معلّمة كغير مقروءة" },
  en: { unread: "unread", options: "Chat options", pinned: "Pinned chat", muted: "Notifications muted", markedUnread: "Marked as unread" },
};

/**
 * One row of the chat list. A row is a div with a real button for opening the
 * chat, so the options button next to it is not nested inside another button.
 */
const KIND_GLYPH = { image: CameraIcon, video: CameraIcon, sticker: CameraIcon, document: FileIcon, file: FileIcon, audio: MicIcon, voice: MicIcon };

export default function ChatListRow({ row, active, lang = "ar", pinnedCount = 0, onOpen, onChange, ConversationAvatar }) {
  const w = WORDS[lang] || WORDS.en;
  const [menuOpen, setMenuOpen] = useState(false);
  const unread = isUnread(row);
  const count = badgeCount(row);
  const muted = isMuted(row);
  const pinned = Boolean(row.pinnedAt);
  const mine = row.lastDirection === "outbound";
  const KindGlyph = KIND_GLYPH[row.lastContentType] || null;

  return (
    <div
      data-testid="chat-row"
      data-unread={unread}
      data-pinned={pinned}
      className={cn("group/row relative flex items-stretch border-b border-[color:var(--wa-bg-chip)] transition-colors hover:bg-[var(--wa-bg-hover)]", active && "bg-[var(--wa-bg-input)]")}
    >
      <button
        type="button"
        aria-pressed={active}
        onClick={onOpen}
        className={cn("flex min-h-[72px] min-w-0 flex-1 gap-3 px-3 py-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--wa-green)]", lang === "ar" ? "text-right" : "text-left")}
      >
        <div className="shrink-0">
          {ConversationAvatar ? (
            <ConversationAvatar conversation={row} className="h-12 w-12 text-[12px]" />
          ) : (
            <div className="grid h-12 w-12 place-items-center rounded-full text-[12px] font-semibold text-[color:var(--wa-text-icon)]" style={{ background: row.color }}>{row.initials}</div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span dir="auto" className={cn("truncate text-[17px] leading-[21px] text-[color:var(--wa-text)]", unread && "font-semibold")}>{row.customer}</span>
            <span dir="ltr" className={cn("shrink-0 text-[12px]", unread && !muted ? "font-medium text-[#1fa855]" : "text-[color:var(--wa-text-secondary)]")}>
              {listTimestamp(row.lastAt, lang)}
            </span>
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1">
            {mine && <MessageStatus status={row.lastStatus} lang={lang} className="shrink-0" />}
            {KindGlyph && <KindGlyph size={16} className="shrink-0 text-[color:var(--wa-text-secondary)]" aria-hidden="true" />}
            <p dir="auto" className={cn("min-w-0 flex-1 truncate text-[14px] leading-[20px]", unread ? "text-[color:var(--wa-text)]" : "text-[color:var(--wa-text-secondary)]")}>{row.preview}</p>
            <span className="flex shrink-0 items-center gap-1.5 text-[color:var(--wa-text-secondary)]">
              {muted && <MuteIcon size={15} role="img" aria-hidden={false} aria-label={w.muted} />}
              {pinned && <PushPinIcon size={15} role="img" aria-hidden={false} aria-label={w.pinned} />}
              {unread && (
                <span
                  data-testid="unread-badge"
                  aria-label={count ? `${count} ${w.unread}` : w.markedUnread}
                  className={cn(
                    "grid place-items-center rounded-full text-[11.5px] font-semibold tabular-nums text-white",
                    count ? "h-5 min-w-5 px-1.5" : "h-3 w-3",
                    muted ? "bg-[var(--wa-text-faint)]" : "bg-[#25d366]",
                  )}
                >
                  {count ? (count > 99 ? "99+" : count) : null}
                </span>
              )}
            </span>
          </div>
        </div>
      </button>
      <div className="relative flex shrink-0 items-end pb-2.5 pe-2">
        <button
          type="button"
          data-testid="row-options"
          aria-label={w.options}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
          className={cn("grid h-10 w-10 place-items-center rounded-full text-[color:var(--wa-text-icon)] sm:h-6 sm:w-6 hover:bg-[var(--wa-bg-hover)] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)] group-hover/row:opacity-100", menuOpen ? "opacity-100" : "opacity-0 [@media(hover:none)]:opacity-100")}
        >
          <ChevronDownIcon size={16} />
        </button>
        {menuOpen && (
          <div className="absolute end-1 top-full z-30">
            <ChatListMenu row={row} lang={lang} pinnedCount={pinnedCount} onChange={onChange} onClose={() => setMenuOpen(false)} />
          </div>
        )}
      </div>
    </div>
  );
}
