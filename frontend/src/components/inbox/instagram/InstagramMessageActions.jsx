import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

// The six quick reactions Instagram offers when you press and hold a message.
export const QUICK_REACTIONS = ["❤️", "😂", "😮", "😢", "😡", "👍"];

const LABEL = {
  react: { en: "React", ar: "تفاعل" },
  reply: { en: "Reply", ar: "رد" },
  copy: { en: "Copy", ar: "نسخ" },
  more: { en: "More", ar: "المزيد" },
  copied: { en: "Copied", ar: "تم النسخ" },
};
const t = (k, lang) => LABEL[k][lang === "ar" ? "ar" : "en"];

function Glyph({ d, className }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d={d} />
    </svg>
  );
}
const SMILE = "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM8.5 14.5a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01";
const REPLY = "M9 14 4 9l5-5M4 9h10a6 6 0 0 1 6 6v3";
const DOTS = "M5 12h.01M12 12h.01M19 12h.01";

// The three small round buttons Instagram shows beside a message on hover (react, reply, more), and
// the emoji strip that opens from the first one. It sits on the side of the bubble facing the
// middle of the chat, so a sent message shows it on its left and a received one on its right.
export function InstagramMessageActions({ m, lang = "ar", mine = "", onReply, onReact, onCopy, visible = false }) {
  const [strip, setStrip] = useState(false);
  const [menu, setMenu] = useState(false);
  const [copied, setCopied] = useState(false);
  const root = useRef(null);
  const out = m.side === "out";

  useEffect(() => {
    if (!strip && !menu) return undefined;
    const close = (e) => { if (root.current && !root.current.contains(e.target)) { setStrip(false); setMenu(false); } };
    const esc = (e) => { if (e.key === "Escape") { setStrip(false); setMenu(false); } };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [strip, menu]);

  if (!onReply && !onReact && !onCopy) return null;
  const btn = "grid h-7 w-7 place-items-center rounded-full text-[#737373] hover:bg-[#efefef] focus-visible:bg-[#efefef] focus-visible:outline-none";

  return (
    <div
      ref={root}
      data-testid="ig-actions"
      dir="ltr"
      className={cn(
        "relative flex items-center transition-opacity",
        out ? "order-first flex-row-reverse" : "order-last",
        visible || strip || menu ? "opacity-100" : "opacity-0 group-hover/ig:opacity-100 group-focus-within/ig:opacity-100",
      )}
    >
      {onReact && (
        <button type="button" data-testid="ig-react" aria-label={t("react", lang)} title={t("react", lang)} aria-expanded={strip} onClick={() => { setMenu(false); setStrip((v) => !v); }} className={btn}>
          <Glyph d={SMILE} />
        </button>
      )}
      {onReply && (
        <button type="button" data-testid="ig-reply" aria-label={t("reply", lang)} title={t("reply", lang)} onClick={() => onReply(m)} className={btn}>
          <Glyph d={REPLY} />
        </button>
      )}
      {onCopy && (
        <button type="button" data-testid="ig-more" aria-label={t("more", lang)} title={t("more", lang)} aria-expanded={menu} onClick={() => { setStrip(false); setMenu((v) => !v); }} className={btn}>
          <Glyph d={DOTS} />
        </button>
      )}
      {strip && (
        <div role="menu" data-testid="ig-reaction-strip" className={cn("absolute bottom-full z-30 mb-1 flex items-center gap-0.5 rounded-full border border-[#dbdbdb] bg-white px-1.5 py-1 shadow-[0_2px_12px_rgba(0,0,0,.15)]", out ? "end-0" : "start-0")}>
          {QUICK_REACTIONS.map((e) => (
            <button
              key={e}
              type="button"
              role="menuitem"
              aria-label={e}
              aria-pressed={mine === e}
              onClick={() => { onReact(e); setStrip(false); }}
              className={cn("grid h-8 w-8 place-items-center rounded-full text-[20px] leading-none transition-transform hover:scale-125", mine === e && "bg-[#efefef]")}
            >
              {e}
            </button>
          ))}
        </div>
      )}
      {menu && (
        <div role="menu" data-testid="ig-more-menu" className={cn("absolute bottom-full z-30 mb-1 min-w-[120px] overflow-hidden rounded-xl border border-[#dbdbdb] bg-white py-1 text-[14px] shadow-[0_2px_12px_rgba(0,0,0,.15)]", out ? "end-0" : "start-0")}>
          <button type="button" role="menuitem" onClick={() => { onCopy(m); setCopied(true); setMenu(false); setTimeout(() => setCopied(false), 1500); }} className="block w-full px-4 py-2 text-start text-[#262626] hover:bg-[#fafafa]">
            {t("copy", lang)}
          </button>
        </div>
      )}
      {copied && <span role="status" className="absolute -top-6 whitespace-nowrap rounded bg-[#262626] px-2 py-0.5 text-[11px] text-white">{t("copied", lang)}</span>}
    </div>
  );
}
