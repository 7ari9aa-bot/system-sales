import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AlertIcon, EmojiIcon, MicIcon, PlusIcon, SendIcon, CloseIcon } from "./icons";
import { composerAvailability, enterSends, lengthWarning, rowsFor, sendable } from "./composerState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: {
    placeholder: "اكتب رسالة", send: "إرسال", emoji: "الرموز التعبيرية", attach: "إرفاق", voice: "تسجيل رسالة صوتية",
    cancelReply: "إلغاء الرد", you: "أنت", customer: "العميل", attachment: "مرفق",
    closed: "انتهت نافذة الـ 24 ساعة. لا يمكن إرسال رسالة حرة، يلزم قالب معتمد.",
    sending: "جارٍ الإرسال", noFiles: "إرسال الملفات والصور والرسائل الصوتية غير متاح بعد من الإنبوكس.",
    left: "متبقي", over: "تجاوزت الحد بمقدار", dismiss: "إغلاق",
  },
  en: {
    placeholder: "Type a message", send: "Send", emoji: "Emoji", attach: "Attach", voice: "Record voice message",
    cancelReply: "Cancel reply", you: "You", customer: "Customer", attachment: "Attachment",
    closed: "The 24-hour window has closed. You cannot send a free-form message, an approved template is required.",
    sending: "Sending", noFiles: "Sending files, photos and voice notes is not available from the inbox yet.",
    left: "left", over: "Over the limit by", dismiss: "Dismiss",
  },
};

/**
 * The WhatsApp input bar. It offers only what actually reaches the customer:
 * text (several lines, Shift+Enter), emoji and replies. Files, photos and voice
 * notes are not sent by the API yet, so the attach and mic buttons say so
 * instead of sending the file's NAME as a message. When the 24-hour window has
 * closed the field is replaced by the reason, since the server would refuse it.
 */
export default function Composer({
  value, onChange, onSend, onToggleEmoji, onCancelReply, replyingTo, customerName,
  lastCustomerMessageAt, sending = false, lang = "ar", now, fontFamily,
}) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const [notice, setNotice] = useState(false);
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

  useEffect(() => { if (!notice) return undefined; const id = setTimeout(() => setNotice(false), 4000); return () => clearTimeout(id); }, [notice]);

  const iconBtn = "grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#54656f] transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] disabled:opacity-50";

  if (closed) {
    return (
      <div data-testid="composer-closed" role="status" dir={lang === "ar" ? "rtl" : "ltr"} style={{ fontFamily }} className="flex items-center gap-3 px-4 py-3 text-[13.5px] text-[#54656f]">
        <AlertIcon size={20} className="shrink-0 text-[#b45309]" />
        <span>{w.closed}</span>
      </div>
    );
  }

  return (
    <div style={{ fontFamily }}>
      {replyingTo && (
        <div data-testid="replying-to" dir="auto" className="mx-2 mt-2 flex items-stretch gap-2 overflow-hidden rounded-lg bg-[#f0f2f5] ring-1 ring-black/5">
          <span aria-hidden="true" className="w-1 shrink-0" style={{ background: replyingTo.side === "out" ? "#06cf9c" : "#53bdeb" }} />
          <div className="min-w-0 flex-1 py-1.5">
            <div className="text-[12.5px] font-medium" style={{ color: replyingTo.side === "out" ? "#06cf9c" : "#53bdeb" }}>{replyingTo.side === "out" ? w.you : (customerName || w.customer)}</div>
            <div className="truncate text-[13px] text-[#667781]">{replyingTo.text || w.attachment}</div>
          </div>
          <button type="button" data-testid="cancel-reply" onClick={onCancelReply} aria-label={w.cancelReply} title={w.cancelReply} className="grid w-9 shrink-0 place-items-center text-[#54656f] hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
            <CloseIcon size={16} />
          </button>
        </div>
      )}

      {notice && (
        <div data-testid="composer-notice" role="status" dir={lang === "ar" ? "rtl" : "ltr"} className="mx-2 mt-2 flex items-start gap-2 rounded-lg bg-[#fff4d6] px-3 py-2 text-[13px] text-[#54450f]">
          <AlertIcon size={16} className="mt-0.5 shrink-0" />
          <span className="flex-1">{w.noFiles}</span>
          <button type="button" onClick={() => setNotice(false)} aria-label={w.dismiss} className="shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"><CloseIcon size={14} /></button>
        </div>
      )}

      <div dir="ltr" className="flex min-h-[52px] items-end gap-1 px-1 py-1.5">
        <button type="button" onClick={onToggleEmoji} aria-label={w.emoji} title={w.emoji} data-testid="composer-emoji" className={iconBtn}><EmojiIcon size={26} /></button>
        <button type="button" onClick={() => setNotice(true)} aria-label={w.attach} title={w.attach} data-testid="composer-attach" className={iconBtn}><PlusIcon size={26} /></button>
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
            className="block max-h-[122px] w-full resize-none rounded-lg border-0 bg-white px-3 py-[11px] text-[15px] leading-5 text-[#111b21] placeholder:text-[#667781] focus:outline-none"
          />
          {warn && (
            <div data-testid="composer-count" aria-live="polite" className={cn("px-1 pt-0.5 text-end text-[12px]", warn.over ? "text-[#ea0038]" : "text-[#667781]")}>
              {warn.over ? `${w.over} ${Math.abs(warn.left)}` : `${warn.left} ${w.left}`}
            </div>
          )}
        </div>
        {value.trim() ? (
          <button type="button" onClick={() => canSend && onSend()} disabled={!canSend} aria-label={sending ? w.sending : w.send} title={w.send} data-testid="composer-send" className={iconBtn}>
            <SendIcon size={24} className={lang === "ar" ? "-scale-x-100" : undefined} />
          </button>
        ) : (
          <button type="button" onClick={() => setNotice(true)} aria-label={w.voice} title={w.voice} data-testid="composer-voice" className={iconBtn}><MicIcon size={24} /></button>
        )}
      </div>
    </div>
  );
}
