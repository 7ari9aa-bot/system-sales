import React, { useEffect, useMemo, useRef, useState } from "react";
import { CloseIcon, SendIcon } from "./icons";
import { buildSend, cannotSendReason, formShape, renderBody } from "./templateForm";

const WORDS = {
  ar: {
    title: "إرسال قالب", close: "إغلاق", search: "ابحث عن قالب", loading: "جارٍ تحميل القوالب",
    failed: "تعذّر تحميل القوالب", retry: "إعادة المحاولة",
    none: "لا توجد قوالب معتمدة بعد. أنشئ قالبًا وانتظر موافقة ميتا عليه.",
    noMatch: "لا يوجد قالب بهذا الاسم", pick: "اختر قالبًا", back: "رجوع", send: "إرسال", sending: "جارٍ الإرسال",
    preview: "معاينة", variable: "المتغير", required: "مطلوب", https: "رابط https:// مطلوب",
    headerMedia: "رابط ملف الترويسة", fileName: "اسم الملف (اختياري)", buttonValue: "قيمة الزر",
    quickReply: "رد سريع", url: "رابط", footer: "التذييل", image: "صورة", video: "فيديو", document: "مستند",
    suffix: "الجزء المتغير من الرابط",
  },
  en: {
    title: "Send a template", close: "Close", search: "Search templates", loading: "Loading templates",
    failed: "Could not load templates", retry: "Try again",
    none: "No approved templates yet. Create one and wait for Meta to approve it.",
    noMatch: "No template with that name", pick: "Choose a template", back: "Back", send: "Send", sending: "Sending",
    preview: "Preview", variable: "Variable", required: "Required", https: "An https:// link is required",
    headerMedia: "Header file link", fileName: "File name (optional)", buttonValue: "Button value",
    quickReply: "Quick reply", url: "Link", footer: "Footer", image: "Image", video: "Video", document: "Document",
    suffix: "The variable part of the link",
  },
};

/**
 * Pick one of the store's APPROVED WhatsApp templates, fill its variables and send it. This is the only
 * way to reach a customer after the 24-hour window, so it has to work from inside the inbox.
 *
 * `loadTemplates()` resolves to the template rows; `onSend({name, language, vars, preview})` resolves to
 * true when the message was accepted (the dialog then closes). Nothing is sent until every field the
 * template asks for is filled: the send button stays off and each empty field says so.
 */
export default function TemplatePicker({ open, onClose, loadTemplates, onSend, lang = "ar", fontFamily }) {
  const w = WORDS[lang] || WORDS.en;
  const [state, setState] = useState({ status: "idle", items: [] });
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState(null);
  const [values, setValues] = useState({});
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);

  const load = async () => {
    setState({ status: "loading", items: [] });
    try {
      const rows = await loadTemplates();
      setState({ status: "ready", items: (rows || []).filter((t) => t.provider === "whatsapp" && !cannotSendReason(t)) });
    } catch (e) {
      setState({ status: "error", items: [], message: e?.message || "" });
    }
  };

  useEffect(() => {
    if (!open) return;
    setQuery(""); setChosen(null); setValues({}); setTouched(false); setBusy(false);
    void load();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose?.(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return state.items.filter((t) => !q || t.name.toLowerCase().includes(q) || (t.body_text || "").toLowerCase().includes(q));
  }, [state.items, query]);

  const shape = chosen ? formShape(chosen) : null;
  const t = (key) => w[key] || key;
  const result = chosen ? buildSend(chosen, values, t) : null;
  const errors = result && !result.ok ? result.errors : {};
  const showError = (key) => (touched ? errors[key] : undefined);

  if (!open) return null;

  const setIn = (group, index, value) => setValues((v) => {
    const next = { ...v };
    if (group === "buttons") next.buttons = { ...(v.buttons || {}), [index]: value };
    else { const list = [...(v[group] || [])]; list[index] = value; next[group] = list; }
    return next;
  });

  const submit = async () => {
    setTouched(true);
    if (!result?.ok || busy) return;
    setBusy(true);
    const ok = await onSend({ name: chosen.name, language: result.language, vars: result.vars, preview: renderBody(chosen, values) });
    setBusy(false);
    if (ok) onClose?.();
  };

  const field = "w-full rounded-lg bg-[var(--wa-bg-input)] px-3 py-2 text-[14px] text-[color:var(--wa-text-primary)] outline-none ring-1 ring-[var(--wa-divider)] focus:ring-2 focus:ring-[var(--wa-ticks-read)]";
  const err = (key) => showError(key) && <div role="alert" className="mt-1 text-[12px] text-[color:var(--wa-danger)]">{showError(key)}</div>;

  return (
    <div role="dialog" aria-modal="true" aria-label={w.title} data-testid="template-picker" dir={lang === "ar" ? "rtl" : "ltr"} style={{ fontFamily }}
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-3" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose?.(); }}>
      <div ref={ref} className="flex max-h-[88vh] w-full max-w-[520px] flex-col overflow-hidden rounded-2xl bg-[var(--wa-bg-panel)] text-[color:var(--wa-text-primary)] shadow-xl">
        <div className="flex items-center gap-2 px-4 py-3">
          <h2 className="flex-1 text-[16px] font-medium">{chosen ? chosen.name : w.title}</h2>
          {chosen && <button type="button" data-testid="template-back" disabled={busy} onClick={() => { setChosen(null); setValues({}); setTouched(false); }} className="rounded-full px-3 py-1 text-[13px] hover:bg-[var(--wa-bg-hover)]">{w.back}</button>}
          <button type="button" data-testid="template-close" aria-label={w.close} title={w.close} disabled={busy} onClick={() => onClose?.()} className="grid h-9 w-9 place-items-center rounded-full hover:bg-[var(--wa-bg-hover)]"><CloseIcon size={18} /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {!chosen && state.status === "loading" && <div role="status" data-testid="template-loading" className="py-8 text-center text-[14px] text-[color:var(--wa-text-secondary)]">{w.loading}</div>}
          {!chosen && state.status === "error" && (
            <div role="alert" data-testid="template-error" className="py-8 text-center text-[14px]">
              <div className="text-[color:var(--wa-danger)]">{w.failed}</div>
              <button type="button" data-testid="template-retry" onClick={() => void load()} className="mt-3 rounded-full bg-[var(--wa-bg-hover)] px-4 py-1.5">{w.retry}</button>
            </div>
          )}
          {!chosen && state.status === "ready" && (
            state.items.length === 0 ? <div data-testid="template-empty" className="py-8 text-center text-[14px] text-[color:var(--wa-text-secondary)]">{w.none}</div> : (
              <>
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={w.search} aria-label={w.search} data-testid="template-search" className={`${field} mb-3`} />
                {shown.length === 0 && <div data-testid="template-no-match" className="py-6 text-center text-[14px] text-[color:var(--wa-text-secondary)]">{w.noMatch}</div>}
                <ul className="space-y-2">
                  {shown.map((tpl) => (
                    <li key={tpl.id}>
                      <button type="button" data-testid={`template-option-${tpl.name}`} onClick={() => { setChosen(tpl); setValues({}); setTouched(false); }}
                        className="block w-full rounded-xl bg-[var(--wa-bg-input)] px-3 py-2.5 text-start hover:bg-[var(--wa-bg-hover)]">
                        <div className="flex items-center gap-2"><span className="text-[14px] font-medium">{tpl.name}</span><span dir="ltr" className="text-[12px] text-[color:var(--wa-text-secondary)]">{tpl.language}</span></div>
                        <div dir="auto" className="mt-0.5 line-clamp-2 text-[13px] text-[color:var(--wa-text-secondary)]">{tpl.body_text}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )
          )}

          {chosen && shape && (
            <div className="space-y-3">
              {shape.header?.kind === "text" && shape.header.slots > 0 && (
                <label className="block"><span className="mb-1 block text-[12.5px] text-[color:var(--wa-text-secondary)]">{shape.header.text}</span>
                  <input data-testid="template-header-1" className={field} value={(values.header || [])[0] || ""} onChange={(e) => setIn("header", 0, e.target.value)} />{err("header.1")}</label>
              )}
              {shape.header && shape.header.kind !== "text" && (
                <div className="space-y-2">
                  <label className="block"><span className="mb-1 block text-[12.5px] text-[color:var(--wa-text-secondary)]">{w.headerMedia} ({w[shape.header.kind]})</span>
                    <input dir="ltr" type="url" inputMode="url" placeholder="https://" data-testid="template-header-media" className={field} value={values.headerMedia?.link || ""} onChange={(e) => setValues((v) => ({ ...v, headerMedia: { ...(v.headerMedia || {}), link: e.target.value } }))} />{err("header.media")}</label>
                  {shape.header.kind === "document" && (
                    <input data-testid="template-header-filename" aria-label={w.fileName} placeholder={w.fileName} className={field} value={values.headerMedia?.filename || ""} onChange={(e) => setValues((v) => ({ ...v, headerMedia: { ...(v.headerMedia || {}), filename: e.target.value } }))} />
                  )}
                </div>
              )}
              {shape.bodySlots.map((n, i) => (
                <label key={n} className="block"><span className="mb-1 block text-[12.5px] text-[color:var(--wa-text-secondary)]">{w.variable} {n}</span>
                  <input data-testid={`template-body-${n}`} dir="auto" className={field} value={(values.body || [])[i] || ""} onChange={(e) => setIn("body", i, e.target.value)} />{err(`body.${n}`)}</label>
              ))}
              {shape.buttons.filter((b) => b.needsInput).map((b) => (
                <label key={b.index} className="block"><span className="mb-1 block text-[12.5px] text-[color:var(--wa-text-secondary)]">{b.text} ({b.type === "url" ? w.suffix : w.quickReply})</span>
                  <input data-testid={`template-button-${b.index}`} dir="auto" className={field} placeholder={b.type === "quick_reply" ? b.text : ""} value={(values.buttons || {})[b.index] ?? ""} onChange={(e) => setIn("buttons", b.index, e.target.value)} />{err(`button.${b.index}`)}</label>
              ))}

              <div className="rounded-xl bg-[var(--wa-bg-input)] p-3">
                <div className="mb-1 text-[12px] text-[color:var(--wa-text-secondary)]">{w.preview}</div>
                <div data-testid="template-preview" dir="auto" className="whitespace-pre-wrap break-words text-[14px]">{renderBody(chosen, values)}</div>
                {shape.footer && <div className="mt-1 text-[12px] text-[color:var(--wa-text-secondary)]">{shape.footer}</div>}
                {shape.buttons.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{shape.buttons.map((b) => <span key={b.index} className="rounded-full bg-[var(--wa-bg-hover)] px-3 py-1 text-[12.5px]">{b.text}</span>)}</div>}
              </div>

              <button type="button" data-testid="template-send" disabled={busy || (touched && !result?.ok)} onClick={() => void submit()}
                className="flex w-full items-center justify-center gap-2 rounded-full bg-[var(--wa-green,#00a884)] px-4 py-2.5 text-[14.5px] font-medium text-white disabled:opacity-50">
                <SendIcon size={18} className={lang === "ar" ? "-scale-x-100" : undefined} />{busy ? w.sending : w.send}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
