/** Bottom composer — Enter sends, Shift+Enter newline, auto-grows to ~6 rows,
 *  disabled while a turn runs. The DRAFT lives in the page (keyed by thread
 *  id) so switching threads never loses what the merchant typed.
 *
 *  Dictation: the mic turns speech into text INSIDE the box (browser speech recognition, no
 *  server). Spoken words never send by themselves: the owner reads them, fixes them, then sends. */

import React from "react";
import { ArrowUp, Mic, Square } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import {
  isVoiceSupported,
  mergeDictation,
  readResults,
  recognitionLang,
  speechRecognitionCtor,
  voiceErrorKey,
} from "./voiceInput";

export default function Composer({ value, onChange, onSend, disabled }) {
  const { t, lang } = useI18n();
  const ref = React.useRef(null);
  const recRef = React.useRef(null);
  const baseRef = React.useRef("");
  const valueRef = React.useRef(value);
  valueRef.current = value;
  const [listening, setListening] = React.useState(false);
  const [voiceError, setVoiceError] = React.useState(null);
  const supported = isVoiceSupported();

  // auto-grow: the textarea tracks its content height up to a ceiling
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const stopListening = React.useCallback(() => {
    const rec = recRef.current;
    recRef.current = null;
    if (rec) {
      rec.onend = null;
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
    setListening(false);
  }, []);

  // leaving the page or being disabled (a turn started) must release the microphone
  React.useEffect(() => stopListening, [stopListening]);
  React.useEffect(() => {
    if (disabled) stopListening();
  }, [disabled, stopListening]);

  const startListening = () => {
    const Ctor = speechRecognitionCtor();
    if (!Ctor || disabled) return;
    setVoiceError(null);
    const rec = new Ctor();
    rec.lang = recognitionLang(lang);
    rec.continuous = true;
    rec.interimResults = true;
    baseRef.current = valueRef.current ?? "";
    rec.onresult = (e) => {
      const { final, interim } = readResults(e.results, 0);
      onChange(mergeDictation(baseRef.current, final + interim));
    };
    rec.onerror = (e) => {
      const key = voiceErrorKey(e?.error);
      if (key) setVoiceError(key);
      stopListening();
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
    };
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      recRef.current = null;
      setVoiceError("salesAssistant.voiceFailed");
    }
  };

  const toggleMic = () => (listening ? stopListening() : startListening());

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    stopListening();
    onSend(text);
    ref.current?.focus();
  };

  return (
    <div data-testid="assistant-composer" className="mx-auto w-full max-w-4xl shrink-0 bg-background px-4 pb-6 pt-2 sm:px-6">
      {voiceError ? (
        <p data-testid="assistant-voice-error" role="alert" className="mb-2 px-3 text-center text-[12.5px] text-destructive">
          {t(voiceError)}
        </p>
      ) : null}
      <div
        data-testid="assistant-composer-field"
        className={`flex items-end gap-1.5 rounded-[32px] border bg-card py-2.5 ps-6 pe-2.5 shadow-[0_6px_24px_-8px_rgba(0,0,0,0.18)] transition-all ${
          disabled
            ? "border-border opacity-70"
            : listening
              ? "border-primary/50 ring-4 ring-primary/10"
              : "border-border focus-within:border-foreground/25 focus-within:shadow-[0_8px_28px_-8px_rgba(0,0,0,0.24)]"
        }`}
      >
        <div className="min-w-0 flex-1">
          {listening ? (
            <span data-testid="assistant-listening" className="mb-0.5 flex items-center gap-1.5 text-[11.5px] font-medium text-primary">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
              {t("salesAssistant.listening")}
            </span>
          ) : null}
          <textarea
            ref={ref}
            rows={1}
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={t("salesAssistant.composerPlaceholder")}
            className="max-h-40 min-h-[44px] w-full resize-none bg-transparent py-2.5 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
          />
        </div>
        {supported ? (
          <button
            type="button"
            data-testid="assistant-mic"
            onClick={toggleMic}
            disabled={disabled}
            aria-pressed={listening}
            aria-label={listening ? t("salesAssistant.micStop") : t("salesAssistant.micStart")}
            title={listening ? t("salesAssistant.micStop") : t("salesAssistant.micStart")}
            className={`grid h-11 w-11 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-40 ${
              listening ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-surface hover:text-foreground"
            }`}
          >
            {listening ? <Square className="h-4 w-4 fill-current" /> : <Mic className="h-5 w-5" />}
          </button>
        ) : null}
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !value.trim()}
          title={t("salesAssistant.send")}
          aria-label={t("salesAssistant.send")}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm transition-all hover:opacity-90 active:scale-95 disabled:opacity-35 disabled:shadow-none"
        >
          <ArrowUp className="h-5 w-5" />
        </button>
      </div>
      <p className="mt-2.5 px-1 text-center text-[11px] text-muted-foreground/70">
        {t("salesAssistant.composerHint")}
      </p>
    </div>
  );
}
