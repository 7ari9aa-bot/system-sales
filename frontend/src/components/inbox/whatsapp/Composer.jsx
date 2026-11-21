import React, { useLayoutEffect, useRef, useState } from "react";
import { AlertIcon, EmojiIcon, MicIcon, PlusIcon, SendIcon, CloseIcon } from "./icons";
import { composerAvailability, enterSends, lengthWarning, rowsFor, sendable } from "./composerState";
import AttachMenu from "./AttachMenu";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: {
    placeholder: "اكتب رسالة", send: "إرسال", emoji: "الرموز التعبيرية", attach: "إرفاق", voice: "تسجيل رسالة صوتية",
    cancelReply: "إلغاء الرد", you: "أنت", customer: "العميل", attachment: "مرفق",
    closed: "انتهت نافذة الـ 24 ساعة. لا يمكن إرسال رسالة حرة، يلزم قالب معتمد.", sendTemplate: "إرسال قالب",
    sending: "جارٍ الإرسال",
    left: "متبقي", over: "تجاوزت الحد بمقدار", dismiss: "إغلاق",
  },
  en: {
    placeholder: "Type a message", send: "Send", emoji: "Emoji", attach: "Attach", voice: "Record voice message",
    cancelReply: "Cancel reply", you: "You", customer: "Customer", attachment: "Attachment",
    closed: "The 24-hour window has closed. You cannot send a free-form message, an approved template is required.", sendTemplate: "Send a template",
    sending: "Sending",
    left: "left", over: "Over the limit by", dismiss: "Dismiss",
  },
};

/**
 * The WhatsApp input bar: text (several lines, Shift+Enter), emoji, replies,
 * files (the + menu) and voice notes (the mic). A picked file or a finished
 * recording is handed up through onPickFile and shown in a preview before it is
 * sent. When the 24-hour window has closed the field is replaced by the
 * reason, since the server would refuse anything sent.
 */
export default function Composer({
  value, onChange, onSend, onToggleEmoji, onCancelReply, replyingTo, customerName,
  lastCustomerMessageAt, sending = false, lang = "ar", now, fontFamily, onPickFile, onStartVoice, onOpenTemplates, onOpenInteractive,
}) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const availability = composerAvailability({ lastCustomerMessageAt, sending, now });
  const closed = availability.reason === "closed";
  const warn = lengthWarning(value);
  const canSend = sendable(value) && availability.canType;

  // Grow with the text up to MAX_ROWS lines, then scroll inside the field.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const line = 20;
    el.style.height = `${Math.min(el.scrollHeight, line * rowsFor(value) + 22)}px`;
  }, [value]);

  const iconBtn = "grid h-10 w-10 shrink-0 place-items-center rounded-full text-[color:var(--wa-text-icon)] transition-colors hover:bg-[var(--wa-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)] disabled:opacity-50";

  if (closed) {
    return (
      <div data-testid="composer-closed" role="status" dir={lang === "ar" ? "rtl" : "ltr"} style={{ fontFamily }} className="flex items-center gap-3 px-4 py-3 text-[13.5px] text-[color:var(--wa-text-icon)]">
        <AlertIcon size={20} className="shrink-0 text-[color:var(--wa-warn)]" />
        <span className="flex-1">{w.closed}</span>
        {onOpenTemplates && (
          <button type="button" data-testid="composer-send-template" onClick={() => onOpenTemplates()} className="shrink-0 rounded-full bg-[var(--wa-green,#00a884)] px-4 py-2 text-[13.5px] font-medium text-white">{w.sendTemplate}</button>
        )}
      </div>
    );
  }

  return (
    <div style={{ fontFamily }} className="relative">
      {replyingTo && (
        <div data-testid="replying-to" dir="auto" className="mx-2 mt-2 flex items-stretch gap-2 overflow-hidden rounded-lg bg-[var(--wa-bg-input)] ring-1 ring-[var(--wa-divider)]">
          <span aria-hidden="true" className="w-1 shrink-0" style={{ background: replyingTo.side === "out" ? "#06cf9c" : "var(--wa-ticks-read)" }} />
          <div className="min-w-0 flex-1 py-1.5">
            <div className="text-[12.5px] font-medium" style={{ color: replyingTo.side === "out" ? "#06cf9c" : "var(--wa-ticks-read)" }}>{replyingTo.side === "out" ? w.you : (customerName || w.customer)}</div>
            <div className="truncate text-[13px] text-[color:var(--wa-text-secondary)]">{replyingTo.text || w.attachment}</div>
          </div>
          <button type="button" data-testid="cancel-reply" onClick={onCancelReply} aria-label={w.cancelReply} title={w.cancelReply} className="grid w-9 shrink-0 place-items-center text-[color:var(--wa-text-icon)] hover:bg-[var(--wa-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">
            <CloseIcon size={16} />
          </button>
        </div>
      )}

      <div className="px-2 pb-2.5 pt-1.5 sm:px-3 sm:pb-3">
      <div dir="ltr" data-testid="composer-capsule" className="flex min-h-[52px] items-end gap-0 rounded-[28px] bg-[var(--wa-bg-capsule)] px-1 py-1 sm:gap-0.5 sm:px-2 shadow-[0_1px_3px_rgba(11,20,26,0.13)]">
        <button type="button" onClick={() => setMenuOpen((v) => !v)} aria-label={w.attach} aria-haspopup="menu" aria-expanded={menuOpen} title={w.attach} data-testid="composer-attach" className={iconBtn}><PlusIcon size={26} className={menuOpen ? "rotate-45 transition-transform" : "transition-transform"} /></button>
        <button type="button" onClick={onToggleEmoji} aria-label={w.emoji} title={w.emoji} data-testid="composer-emoji" className={iconBtn}><EmojiIcon size={26} /></button>
        <AttachMenu open={menuOpen} onClose={() => setMenuOpen(false)} onPick={(file, opts) => onPickFile?.(file, opts)} onOpenTemplates={onOpenTemplates} onOpenInteractive={onOpenInteractive} lang={lang} />
        <div className="mx-1 min-w-0 flex-1">
          <textarea
            ref={ref}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            dir="auto"
            onKeyDown={(e) => {
              if (e.key === "Escape" && replyingTo) { onCancelReply?.(); return; }
              if (enterSends(e)) { e.preventDefault(); if (canSend) onSend(); }
            }}
            placeholder={w.placeholder}
            aria-label={w.placeholder}
            aria-invalid={warn?.over || undefined}
            data-testid="composer-input"
            readOnly={sending}
            className="block max-h-[122px] w-full resize-none rounded-none border-0 bg-transparent px-1.5 py-[13px] sm:px-2 text-[15px] leading-5 text-[color:var(--wa-text)] placeholder:text-[color:var(--wa-text-secondary)] focus:outline-none"
          />
          {warn && (
            <div data-testid="composer-count" aria-live="polite" className={cn("px-1 pt-0.5 text-end text-[12px]", warn.over ? "text-[color:var(--wa-danger)]" : "text-[color:var(--wa-text-secondary)]")}>
              {warn.over ? `${w.over} ${Math.abs(warn.left)}` : `${warn.left} ${w.left}`}
            </div>
          )}
        </div>
        {value.trim() ? (
          <button type="button" onClick={() => canSend && onSend()} disabled={!canSend} aria-label={sending ? w.sending : w.send} title={w.send} data-testid="composer-send" className={iconBtn}>
            <SendIcon size={24} className={lang === "ar" ? "-scale-x-100" : undefined} />
          </button>
        ) : (
          <button type="button" onClick={() => onStartVoice?.()} aria-label={w.voice} title={w.voice} data-testid="composer-voice" className={iconBtn}><MicIcon size={24} /></button>
        )}
      </div>
      </div>
    </div>
  );
}
