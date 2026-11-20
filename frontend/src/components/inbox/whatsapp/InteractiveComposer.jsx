import React, { useEffect, useMemo, useState } from "react";
import { CloseIcon, SendIcon } from "./icons";
import { InteractiveBody } from "./MessageBodies";
import {
  KINDS, LIMITS, bodyLimit, buildInteractive, canAddButton, canAddRow, canAddSection, draftDisplay, emptyForm, switchKind,
} from "./interactiveForm";

const WORDS = {
  ar: {
    title: "رسالة بأزرار أو قائمة", close: "إغلاق", send: "إرسال", sending: "جارٍ الإرسال",
    kind: "النوع", buttons: "أزرار رد", list: "قائمة", cta_url: "زر رابط",
    header: "العنوان (اختياري)", body: "نص الرسالة", footer: "التذييل (اختياري)",
    buttonTitle: "نص الزر", addButton: "إضافة زر", remove: "حذف",
    listButton: "نص زر القائمة", sectionTitle: "عنوان القسم", rowTitle: "عنوان الصف", rowDescription: "الوصف (اختياري)",
    addSection: "إضافة قسم", addRow: "إضافة صف", label: "نص الزر", url: "الرابط",
    preview: "المعاينة", required: "مطلوب", tooLong: "الحد الأقصى {max} حرفًا", duplicate: "نص مكرر",
    atLeastOne: "أضف واحدًا على الأقل", tooMany: "الحد الأقصى {max}", tooManyRows: "الحد الأقصى {max} صفوف في القائمة كلها",
    badUrl: "رابط كامل يبدأ بـ https://", outside: "خارج نافذة الـ24 ساعة: أرسل قالبًا معتمدًا بدلًا من ذلك.",
    hintButtons: "حتى 3 أزرار. العميل يضغط فيصلك ردّه.", hintList: "حتى 10 صفوف إجمالًا. العميل يختار صفًا واحدًا.", hintCta: "زر واحد يفتح رابطًا.",
    count: "{n} من {max}",
  },
  en: {
    title: "Message with buttons or a list", close: "Close", send: "Send", sending: "Sending",
    kind: "Type", buttons: "Reply buttons", list: "List", cta_url: "Link button",
    header: "Header (optional)", body: "Message text", footer: "Footer (optional)",
    buttonTitle: "Button text", addButton: "Add button", remove: "Remove",
    listButton: "List button text", sectionTitle: "Section title", rowTitle: "Row title", rowDescription: "Description (optional)",
    addSection: "Add section", addRow: "Add row", label: "Button text", url: "Link",
    preview: "Preview", required: "Required", tooLong: "At most {max} characters", duplicate: "Repeats another",
    atLeastOne: "Add at least one", tooMany: "At most {max}", tooManyRows: "At most {max} rows in the whole list",
    badUrl: "A full link starting with https://", outside: "Outside the 24-hour window: send an approved template instead.",
    hintButtons: "Up to 3 buttons. The customer taps one and you get their choice.", hintList: "Up to 10 rows in total. The customer picks one.", hintCta: "One button that opens a link.",
    count: "{n} of {max}",
  },
};

const fill = (s, vars) => Object.entries(vars || {}).reduce((out, [k, v]) => out.replace(`{${k}}`, v), s);

/**
 * Compose a WhatsApp message with reply buttons, a list, or a link button, and send it.
 *
 * `onSend(spec)` resolves to true when the message was accepted (the dialog then closes). Nothing is
 * sent until every field passes the same limits the server enforces; each wrong field says why, and
 * every Add button stops at its limit. The preview is the real bubble, drawn from the real shape.
 */
export default function InteractiveComposer({ open, onClose, onSend, lang = "ar", fontFamily, windowOpen = true, sendError = "" }) {
  const w = WORDS[lang] || WORDS.en;
  const [form, setForm] = useState(() => emptyForm("buttons"));
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(emptyForm("buttons")); setTouched(false); setBusy(false);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape" && !busy) onClose?.(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  const result = useMemo(() => buildInteractive(form, (key, vars) => fill((WORDS[lang] || WORDS.en)[key] || key, vars)), [form, lang]);
  const errors = result.ok ? {} : result.errors;
  const showError = (path) => (touched ? errors[path] : undefined);
  const previewSpec = useMemo(() => draftDisplay(form), [form]);

  if (!open) return null;

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const setButton = (i, patch) => set({ buttons: form.buttons.map((b, j) => (j === i ? { ...b, ...patch } : b)) });
  const setSection = (si, patch) => set({ sections: form.sections.map((s, j) => (j === si ? { ...s, ...patch } : s)) });
  const setRow = (si, ri, patch) => setSection(si, { rows: form.sections[si].rows.map((r, j) => (j === ri ? { ...r, ...patch } : r)) });

  const submit = async () => {
    setTouched(true);
    if (!result.ok || busy || !windowOpen) return;
    setBusy(true);
    let ok = false;
    try {
      ok = await onSend(result.spec);
    } finally {
      setBusy(false);
    }
    if (ok) onClose?.();
  };

  const field = "w-full rounded-lg bg-[var(--wa-bg-input)] px-3 py-2 text-[14px] text-[color:var(--wa-text-primary)] outline-none ring-1 ring-[var(--wa-divider)] focus:ring-[var(--wa-green-link)]";
  const small = "rounded-full bg-[var(--wa-bg-hover)] px-3 py-1 text-[13px] disabled:opacity-40";
  const err = (path) => showError(path) && <div role="alert" data-testid={`err-${path}`} className="mt-1 text-[12px] text-[color:var(--wa-danger)]">{showError(path)}</div>;
  const label = (text, extra) => <div className="mb-1 mt-3 flex items-center justify-between text-[12.5px] text-[color:var(--wa-text-secondary)]"><span>{text}</span>{extra}</div>;
  const hint = { buttons: w.hintButtons, list: w.hintList, cta_url: w.hintCta }[form.kind];

  return (
    <div role="dialog" aria-modal="true" aria-label={w.title} data-testid="interactive-composer" dir={lang === "ar" ? "rtl" : "ltr"} style={{ fontFamily }}
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-3" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose?.(); }}>
      <div className="flex max-h-[90vh] w-full max-w-[560px] flex-col overflow-hidden rounded-2xl bg-[var(--wa-bg-panel)] text-[color:var(--wa-text-primary)] shadow-xl">
        <div className="flex items-center gap-2 px-4 py-3">
          <h2 className="flex-1 text-[16px] font-medium">{w.title}</h2>
          <button type="button" data-testid="interactive-close" aria-label={w.close} title={w.close} disabled={busy} onClick={() => onClose?.()} className="grid h-9 w-9 place-items-center rounded-full hover:bg-[var(--wa-bg-hover)]"><CloseIcon size={20} /></button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {!windowOpen && <div role="alert" data-testid="interactive-outside" className="mb-2 rounded-lg bg-[var(--wa-bg-hover)] px-3 py-2 text-[13px]">{w.outside}</div>}

          <div role="radiogroup" aria-label={w.kind} className="flex gap-1.5">
            {KINDS.map((k) => (
              <button key={k} type="button" role="radio" aria-checked={form.kind === k} data-testid={`kind-${k}`} onClick={() => setForm((f) => switchKind(f, k))}
                className={`flex-1 rounded-full px-3 py-1.5 text-[13.5px] ${form.kind === k ? "bg-[var(--wa-green-link)] text-white" : "bg-[var(--wa-bg-hover)]"}`}>{w[k]}</button>
            ))}
          </div>
          <div className="mt-1.5 text-[12px] text-[color:var(--wa-text-secondary)]">{hint}</div>

          {label(w.header)}
          <input data-testid="f-header" value={form.header} maxLength={LIMITS.headerText * 2} onChange={(e) => set({ header: e.target.value })} className={field} dir="auto" />
          {err("header")}

          {label(w.body, <span dir="ltr">{[...form.body].length}/{bodyLimit(form.kind)}</span>)}
          <textarea data-testid="f-body" rows={3} value={form.body} onChange={(e) => set({ body: e.target.value })} className={field} dir="auto" />
          {err("body")}

          {form.kind === "buttons" && (
            <>
              {label(w.buttons, <span dir="ltr">{form.buttons.length}/{LIMITS.buttons}</span>)}
              <div className="space-y-2">
                {form.buttons.map((b, i) => (
                  <div key={i}>
                    <div className="flex gap-2">
                      <input data-testid={`f-button-${i}`} aria-label={`${w.buttonTitle} ${i + 1}`} value={b.title} onChange={(e) => setButton(i, { title: e.target.value })} className={field} dir="auto" />
                      <button type="button" data-testid={`rm-button-${i}`} aria-label={`${w.remove} ${i + 1}`} disabled={form.buttons.length <= 1} onClick={() => set({ buttons: form.buttons.filter((_, j) => j !== i) })} className={small}>{w.remove}</button>
                    </div>
                    {err(`buttons.${i}.title`)}
                  </div>
                ))}
              </div>
              {err("buttons")}
              <button type="button" data-testid="add-button" disabled={!canAddButton(form)} onClick={() => set({ buttons: [...form.buttons, { title: "" }] })} className={`${small} mt-2`}>{w.addButton}</button>
            </>
          )}

          {form.kind === "list" && (
            <>
              {label(w.listButton)}
              <input data-testid="f-list-button" value={form.listButton} onChange={(e) => set({ listButton: e.target.value })} className={field} dir="auto" />
              {err("listButton")}
              {err("rows")}
              {err("sections")}
              {form.sections.map((s, si) => (
                <div key={si} data-testid={`section-${si}`} className="mt-3 rounded-xl bg-[var(--wa-bg-hover)] p-3">
                  <div className="flex gap-2">
                    <input data-testid={`f-section-${si}`} aria-label={`${w.sectionTitle} ${si + 1}`} placeholder={w.sectionTitle} value={s.title} onChange={(e) => setSection(si, { title: e.target.value })} className={field} dir="auto" />
                    <button type="button" data-testid={`rm-section-${si}`} aria-label={`${w.remove} ${w.sectionTitle} ${si + 1}`} disabled={form.sections.length <= 1} onClick={() => set({ sections: form.sections.filter((_, j) => j !== si) })} className={small}>{w.remove}</button>
                  </div>
                  {err(`sections.${si}.title`)}
                  {err(`sections.${si}.rows`)}
                  <div className="mt-2 space-y-2">
                    {s.rows.map((r, ri) => (
                      <div key={ri} className="rounded-lg bg-[var(--wa-bg-panel)] p-2">
                        <div className="flex gap-2">
                          <input data-testid={`f-row-${si}-${ri}`} aria-label={`${w.rowTitle} ${ri + 1}`} placeholder={w.rowTitle} value={r.title} onChange={(e) => setRow(si, ri, { title: e.target.value })} className={field} dir="auto" />
                          <button type="button" data-testid={`rm-row-${si}-${ri}`} aria-label={`${w.remove} ${w.rowTitle} ${ri + 1}`} disabled={s.rows.length <= 1} onClick={() => setSection(si, { rows: s.rows.filter((_, j) => j !== ri) })} className={small}>{w.remove}</button>
                        </div>
                        {err(`sections.${si}.rows.${ri}.title`)}
                        <input data-testid={`f-desc-${si}-${ri}`} aria-label={`${w.rowDescription} ${ri + 1}`} placeholder={w.rowDescription} value={r.description} onChange={(e) => setRow(si, ri, { description: e.target.value })} className={`${field} mt-1.5`} dir="auto" />
                        {err(`sections.${si}.rows.${ri}.description`)}
                      </div>
                    ))}
                  </div>
                  <button type="button" data-testid={`add-row-${si}`} disabled={!canAddRow(form)} onClick={() => setSection(si, { rows: [...s.rows, { title: "", description: "" }] })} className={`${small} mt-2`}>{w.addRow}</button>
                </div>
              ))}
              <button type="button" data-testid="add-section" disabled={!canAddSection(form)} onClick={() => set({ sections: [...form.sections, { title: "", rows: [{ title: "", description: "" }] }] })} className={`${small} mt-3`}>{w.addSection}</button>
            </>
          )}

          {form.kind === "cta_url" && (
            <>
              {label(w.label)}
              <input data-testid="f-label" value={form.label} onChange={(e) => set({ label: e.target.value })} className={field} dir="auto" />
              {err("label")}
              {label(w.url)}
              <input data-testid="f-url" type="url" inputMode="url" placeholder="https://" value={form.url} onChange={(e) => set({ url: e.target.value })} className={field} dir="ltr" />
              {err("url")}
            </>
          )}

          {label(w.footer)}
          <input data-testid="f-footer" value={form.footer} onChange={(e) => set({ footer: e.target.value })} className={field} dir="auto" />
          {err("footer")}

          {label(w.preview)}
          <div data-testid="interactive-preview" className="rounded-xl bg-[var(--wa-bubble-out)] p-3 text-[14px]">
            {form.body.trim() ? <InteractiveBody message={previewSpec} lang={lang} /> : <span className="text-[color:var(--wa-text-secondary)]">{w.body}</span>}
          </div>
          {sendError && <div role="alert" data-testid="interactive-send-error" className="mt-2 text-[13px] text-[color:var(--wa-danger)]">{sendError}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-[color:var(--wa-divider)] px-4 py-3">
          <button type="button" data-testid="interactive-send" disabled={busy || !windowOpen} onClick={() => void submit()}
            className="flex items-center gap-2 rounded-full bg-[var(--wa-green-link)] px-5 py-2 text-[14px] font-medium text-white disabled:opacity-50">
            <SendIcon size={16} />{busy ? w.sending : w.send}
          </button>
        </div>
      </div>
    </div>
  );
}
