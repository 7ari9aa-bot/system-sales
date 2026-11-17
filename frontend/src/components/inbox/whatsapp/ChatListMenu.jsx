import React, { useEffect, useRef, useState } from "react";
import { ArchiveIcon, MuteIcon, PushPinIcon, UnreadIcon } from "./icons";
import { isMuted } from "./chatListState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: {
    menu: "خيارات المحادثة", pin: "تثبيت المحادثة", unpin: "إلغاء تثبيت المحادثة",
    mute: "كتم الإشعارات", unmute: "إلغاء كتم الإشعارات", archive: "أرشفة المحادثة", unarchive: "إلغاء الأرشفة",
    unread: "تعليم كغير مقروءة", read: "تعليم كمقروءة",
    "8h": "8 ساعات", "1w": "أسبوع", always: "دائمًا", muteFor: "كتم الإشعارات لمدة",
    pinLimit: "يمكن تثبيت 3 محادثات فقط",
  },
  en: {
    menu: "Chat options", pin: "Pin chat", unpin: "Unpin chat",
    mute: "Mute notifications", unmute: "Unmute notifications", archive: "Archive chat", unarchive: "Unarchive chat",
    unread: "Mark as unread", read: "Mark as read",
    "8h": "8 hours", "1w": "1 week", always: "Always", muteFor: "Mute notifications for",
    pinLimit: "You can only pin 3 chats",
  },
};

export const MAX_PINNED = 3;

/**
 * The actions on one chat: pin, mute, archive, mark unread. Pure of side
 * effects: it reports the change as a `list-state` body through `onChange` and
 * closes. The caller sends it to the server and updates the list on success.
 */
export default function ChatListMenu({ row, lang = "ar", pinnedCount = 0, onChange, onClose }) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const [muteOpen, setMuteOpen] = useState(false);
  const muted = isMuted(row);
  const pinned = Boolean(row.pinnedAt);
  const archived = Boolean(row.archivedAt);
  const unread = (Number(row.unread) || 0) > 0 || Boolean(row.markedUnread);
  const pinBlocked = !pinned && pinnedCount >= MAX_PINNED;

  useEffect(() => {
    ref.current?.querySelector("button:not([disabled])")?.focus();
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); onClose?.(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const items = [...(ref.current?.querySelectorAll("button:not([disabled])") || [])];
      if (!items.length) return;
      e.preventDefault();
      const at = items.indexOf(document.activeElement);
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) onClose?.(); }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [onClose]);

  const choose = (body) => () => { onChange?.(body); onClose?.(); };
  const item = "flex w-full items-center gap-3 px-4 py-2.5 text-start text-[14px] text-[#111b21] hover:bg-[#f5f6f6] focus-visible:bg-[#f5f6f6] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div ref={ref} role="menu" aria-label={w.menu} data-testid="chat-list-menu" className="min-w-[210px] overflow-hidden rounded-xl bg-white py-1.5 shadow-lg ring-1 ring-black/5">
      {muteOpen ? (
        <div role="group" aria-label={w.muteFor}>
          <div className="px-4 py-2 text-[12.5px] text-[#667781]">{w.muteFor}</div>
          {["8h", "1w", "always"].map((d) => (
            <button key={d} type="button" role="menuitem" data-testid={`mute-${d}`} className={item} onClick={choose({ mute: d })}>
              {w[d]}
            </button>
          ))}
        </div>
      ) : (
        <>
          <button type="button" role="menuitem" data-testid="act-archive" className={item} onClick={choose({ archived: !archived })}>
            <ArchiveIcon size={18} className="text-[#54656f]" />{archived ? w.unarchive : w.archive}
          </button>
          {muted ? (
            <button type="button" role="menuitem" data-testid="act-unmute" className={item} onClick={choose({ mute: "off" })}>
              <MuteIcon size={18} className="text-[#54656f]" />{w.unmute}
            </button>
          ) : (
            <button type="button" role="menuitem" data-testid="act-mute" className={item} onClick={() => setMuteOpen(true)}>
              <MuteIcon size={18} className="text-[#54656f]" />{w.mute}
            </button>
          )}
          <button
            type="button" role="menuitem" data-testid="act-pin" disabled={pinBlocked}
            title={pinBlocked ? w.pinLimit : undefined}
            className={cn(item)} onClick={choose({ pinned: !pinned })}
          >
            <PushPinIcon size={18} className="text-[#54656f]" />{pinned ? w.unpin : w.pin}
          </button>
          <button type="button" role="menuitem" data-testid="act-unread" className={item} onClick={choose({ marked_unread: !unread })}>
            <UnreadIcon size={18} className="text-[#54656f]" />{unread ? w.read : w.unread}
          </button>
        </>
      )}
    </div>
  );
}
