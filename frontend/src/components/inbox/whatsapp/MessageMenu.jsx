import React, { useEffect, useRef } from "react";
import { CopyIcon, ReplyIcon } from "./icons";
import { cn } from "@/lib/utils";

// The six quick reactions WhatsApp offers first.
export const QUICK_REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

const WORDS = {
  ar: { reply: "رد", copy: "نسخ", menu: "خيارات الرسالة", react: "تفاعل بـ", remove: "إزالة التفاعل" },
  en: { reply: "Reply", copy: "Copy", menu: "Message options", react: "React with", remove: "Remove reaction" },
};

/**
 * The menu that opens on a message: quick reactions on top, then Reply / Copy.
 * Pure of side effects: it reports a choice through callbacks and closes itself.
 * `mine` is the emoji we already reacted with; choosing it again withdraws it,
 * as in WhatsApp.
 */
export default function MessageMenu({ m, lang = "ar", mine = "", canReact = true, onReply, onCopy, onReact, onClose }) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const hasText = Boolean((m.text || "").trim()) && !String(m.text).startsWith("blob:");

  useEffect(() => {
    const first = ref.current?.querySelector("button");
    first?.focus();
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); onClose?.(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const items = [...(ref.current?.querySelectorAll("button") || [])];
      if (!items.length) return;
      e.preventDefault();
      const at = items.indexOf(document.activeElement);
      const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : -1;
      items[(at + step + items.length) % items.length].focus();
    }
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) onClose?.(); }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [onClose]);

  const done = (fn) => () => { fn?.(); onClose?.(); };

  return (
    <div ref={ref} role="menu" aria-label={w.menu} data-testid="message-menu" className="flex flex-col gap-1.5">
      {canReact && (
        <div role="group" className="flex items-center gap-0.5 rounded-full bg-[var(--wa-bg-panel)] px-1.5 py-1 shadow-lg ring-1 ring-[var(--wa-divider)]">
          {QUICK_REACTIONS.map((emoji) => (
            <button
              key={emoji}
              type="button"
              role="menuitem"
              data-testid="quick-reaction"
              aria-label={mine === emoji ? `${w.remove} ${emoji}` : `${w.react} ${emoji}`}
              aria-pressed={mine === emoji}
              onClick={done(() => onReact?.(mine === emoji ? "" : emoji))}
              className={cn("grid h-9 w-9 place-items-center rounded-full text-[22px] leading-none transition-transform hover:scale-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]", mine === emoji && "bg-[#e7f8f3]")}
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
      <div className="min-w-[160px] overflow-hidden rounded-xl bg-[var(--wa-bg-panel)] py-1.5 text-[14.5px] text-[color:var(--wa-text)] shadow-lg ring-1 ring-[var(--wa-divider)]">
        <button type="button" role="menuitem" data-testid="menu-reply" onClick={done(() => onReply?.(m))} className="flex w-full items-center gap-3 px-4 py-2 text-start hover:bg-[var(--wa-bg-hover)] focus-visible:bg-[var(--wa-bg-hover)] focus-visible:outline-none">
          <ReplyIcon size={18} />
          <span>{w.reply}</span>
        </button>
        {hasText && (
          <button type="button" role="menuitem" data-testid="menu-copy" onClick={done(() => onCopy?.(m))} className="flex w-full items-center gap-3 px-4 py-2 text-start hover:bg-[var(--wa-bg-hover)] focus-visible:bg-[var(--wa-bg-hover)] focus-visible:outline-none">
            <CopyIcon size={18} />
            <span>{w.copy}</span>
          </button>
        )}
      </div>
    </div>
  );
}
