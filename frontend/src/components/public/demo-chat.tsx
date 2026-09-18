"use client";

/** شات تفاعلي تجريبي في الـHero — بدون أي أسماء أو بيانات حقيقية.
 *  المستخدم يكتب و"المساعد" يرد بردود محاكاة محلية حسب كلمات مفتاحية.
 *  كل الردود من قاموس i18n — مفيش أي نداءات شبكة. */

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/components/public/i18n";

type Msg = { id: number; from: "user" | "bot"; text: string };

export function DemoChat() {
  const { t, locale } = useI18n();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);

  // رسالة الترحيب + إعادة التهيئة عند تغيير اللغة
  useEffect(() => {
    idRef.current = 1;
    setThinking(false);
    setBusy(false);
    setMsgs([{ id: 0, from: "bot", text: t.chat.greeting }]);
  }, [t.chat.greeting]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs, thinking]);

  function replyFor(text: string): string {
    const q = text.toLowerCase();
    const has = (...words: string[]) => words.some((w) => q.includes(w));
    if (has("سعر", "أسعار", "اسعار", "خطط", "plan", "price", "cost", "تكلفة", "مجاني", "free"))
      return t.chat.r_pricing;
    if (has("أتمتة", "اتمتة", "أتمته", "automation", "workflow", "مسار", "سير عمل"))
      return t.chat.r_automation;
    if (has("أمان", "امان", "security", "حماية", "خصوصية", "privacy", "تدقيق", "audit"))
      return t.chat.r_security;
    if (has("قناة", "قنوات", "واتساب", "whatsapp", "channel", "تليجرام", "telegram", "انستجرام", "instagram"))
      return t.chat.r_channels;
    if (has("إيه", "ايه", "ما هو", "what is", "who are you", "مين انت", "fihrist", "فهرست", "intro", "تعريف"))
      return t.chat.r_intro;
    return t.chat.r_fallback;
  }

  function send(raw?: string) {
    const text = (raw ?? input).trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((m) => [...m, { id: ++idRef.current, from: "user", text }]);
    setThinking(true);
    const delay = 700 + Math.min(text.length * 15, 900);
    window.setTimeout(() => {
      setThinking(false);
      setMsgs((m) => [...m, { id: ++idRef.current, from: "bot", text: replyFor(text) }]);
      setBusy(false);
    }, delay);
  }

  return (
    <div className="fh-chat-wrap">
      <div className="fh-demo-chip" style={{ marginInlineStart: 0, marginBottom: ".8rem" }}>
        <span className="fh-demo-dot" /> {t.hero.demo}
      </div>

      <div className="fh-chat" role="region" aria-label={t.chat.title}>
        <div className="fh-chat-head">
          <span className="fh-chat-avatar" aria-hidden="true">F</span>
          <span className="fh-chat-title">
            <strong>{t.chat.title}</strong>
            <small><span className="fh-status-dot" aria-hidden="true" /> {t.chat.status}</small>
          </span>
          <span className="fh-chat-badge">{locale === "ar" ? "محاكاة" : "Simulated"}</span>
        </div>

        <div className="fh-chat-msgs" ref={listRef} aria-live="polite">
          {msgs.map((m) => (
            <div key={m.id} className={`fh-bubble fh-msg-in${m.from === "user" ? " fh-bubble-user" : ""}`}>
              {m.text}
              <span className="fh-bubble-tag">
                {m.from === "user"
                  ? (locale === "ar" ? "أنت" : "You")
                  : (locale === "ar" ? "مساعد FIHRIST · عرض تجريبي" : "FIHRIST assistant · demo")}
              </span>
            </div>
          ))}
          {thinking && (
            <div className="fh-typing" aria-hidden="true">
              <span /><span /><span />
            </div>
          )}
        </div>

        <div className="fh-chat-suggest">
          {[t.chat.s1, t.chat.s2, t.chat.s3].map((s) => (
            <button key={s} className="fh-suggest-chip" onClick={() => send(s)} disabled={busy}>
              {s}
            </button>
          ))}
        </div>

        <form
          className="fh-chat-input"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t.chat.ph}
            aria-label={t.chat.ph}
            maxLength={300}
          />
          <button className="fh-btn" disabled={busy || !input.trim()} type="submit">
            {t.chat.send}
          </button>
        </form>

        <div className="fh-chat-tools">
          <h4>{t.chat.toolsTitle}</h4>
          <div className="fh-tools-row">
            {t.chat.tools.map((tool) => (
              <span key={tool} className="fh-tool-chip">{tool}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
