/** Bottom composer — Enter sends, Shift+Enter newline, auto-grows to ~6 rows,
 *  disabled while a turn runs. The DRAFT lives in the page (keyed by thread
 *  id) so switching threads never loses what the merchant typed.
 *
 *  Dictation: the mic turns speech into text INSIDE the box (browser speech recognition, no
 *  server). Spoken words never send by themselves: the owner reads them, fixes them, then sends. */

import React from "react";
import { ArrowUp, AudioLines, Mic, Plus, Square, VolumeX } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { MIC_ERROR_TEXT, openVoiceSession, startBrowserCall, STREAM_STATE } from "@/voice/browserCall";
import VoiceScreen from "@/voice/VoiceScreen";
import { createLevelMeter } from "@/voice/orb/levels";
import { createCallController } from "./callControl";
import { ATTACH_EXTENSIONS, checkAttachment, mergeAttachment } from "./fileAttach";
import {
  isVoiceSupported,
  mergeDictation,
  readResults,
  recognitionLang,
  speechRecognitionCtor,
  voiceErrorKey,
} from "./voiceInput";

export default function Composer({ value, onChange, onSend, disabled, error, onCallEnd, threadId }) {
  const { t, lang } = useI18n();
  const ref = React.useRef(null);
  const recRef = React.useRef(null);
  const baseRef = React.useRef("");
  const valueRef = React.useRef(value);
  valueRef.current = value;
  const [listening, setListening] = React.useState(false);
  const [voiceError, setVoiceError] = React.useState(null);
  const [attachError, setAttachError] = React.useState(null);
  const fileRef = React.useRef(null);
  const supported = isVoiceSupported();
  // مكالمة حقيقية: المايك هنا بيبعت صوت للسيرفر، مش بيحوّل كلام لنص زي زر الإملاء.
  const controllerRef = React.useRef(null);
  // مفتاح ثابت للشاشة: الدوسة التانية تكمّل نفس الجلسة بدل ما تفتح مكالمة تانية مدفوعة.
  const clientKeyRef = React.useRef(
    typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `screen-${Date.now()}`,
  );
  const [calling, setCalling] = React.useState(false);
  const [callError, setCallError] = React.useState(null);
  // شاشة المكالمة: بتفتح مع الدوسة، وبتفضل مفتوحة لو السيرفر رفض عشان الرسالة تتقري.
  const [screenOpen, setScreenOpen] = React.useState(false);
  const [callState, setCallState] = React.useState(STREAM_STATE.IDLE);
  // أثر السوكت: لما المكالمة تفشل، السبب الحقيقي لازم يبان بدل رسالة عامة.
  const [socketNote, setSocketNote] = React.useState("");
  // دليل الصوت: عدد حزم صوت المساعد اللي وصلت. صفر معناها السوكت فتح بس.
  const [audioNote, setAudioNote] = React.useState("");
  // المايك المعلّق: المتصفح مش بيشغّل الصوت قبل دوسة، والشاشة لازم تقول كده.
  const [micPrompt, setMicPrompt] = React.useState(false);
  // سبب فشل المايك بكود: الشاشة كانت بتفضل تقول "جارٍ تهيئة الميكروفون" للأبد.
  const [micError, setMicError] = React.useState("");

  const onCallEndRef = React.useRef(onCallEnd);
  onCallEndRef.current = onCallEnd;

  // المحادثة المفتوحة دلوقتي: المكالمة تكمّلها بدل ما تفتح واحدة جديدة.
  const threadIdRef = React.useRef(threadId);
  threadIdRef.current = threadId;

  // عدّاد صوت واحد للمكالمة: المايك وصوت المساعد بيكتبوا فيه، والكرة بتقرأ منه كل فريم.
  // مش state — الصوت بيوصل 20 مرة في الثانية، وإعادة رسم الشجرة مع كل حزمة هتقتل الأداء.
  const meterRef = React.useRef(null);
  if (!meterRef.current) meterRef.current = createLevelMeter();

  if (!controllerRef.current) {
    controllerRef.current = createCallController({
      openSession: () =>
        openVoiceSession({ clientKey: clientKeyRef.current, threadId: threadIdRef.current }),
      startCall: (options) =>
        startBrowserCall({
          ...options,
          onSocket: (event) =>
            setSocketNote(event.type === "close" ? `قناة الصوت: مغلقة (${event.code ?? "?"})` : `قناة الصوت: ${event.type === "open" ? "متصلة" : "غير متاحة"}`),
          onAudio: ({ frames }) => {
            setMicPrompt(false);
            setAudioNote(`صوت المساعد: ${frames} حزمة`);
          },
          onLevel: (levels) => {
            const meter = meterRef.current;
            if (levels?.assistant != null) meter.setAssistant(levels.assistant);
            if (levels?.mic != null) meter.setMic(levels.mic);
          },
          onNeedsGesture: () => setMicPrompt(true),
          onMicError: ({ code }) => {
            setMicPrompt(false);
            setMicError(code);
          },
        }),
      // الجلسة المحفوظة لو بقت مش موجودة، المفتاح بيتبدّل فبتفتح جلسة جديدة.
      resetSession: async () => {
        clientKeyRef.current =
          typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `screen-${Date.now()}`;
      },
      onChange: ({ calling: next, error, state }) => {
        setCalling(next);
        setCallError(error);
        if (state) setCallState(state);
      },
      onEnd: () => {
        onCallEndRef.current?.();
        setScreenOpen(false);
        setMicPrompt(false);
        setMicError("");
        setAudioNote("");
      },
    });
  }

  const toggleCall = React.useCallback(() => {
    if (controllerRef.current?.calling) setScreenOpen(false);
    else {
      setCallError(null);
      setCallState(STREAM_STATE.OPENING);
      setMicPrompt(false);
      setMicError("");
      setAudioNote("");
      setScreenOpen(true);
    }
    controllerRef.current?.toggle();
  }, []);

  const closeScreen = React.useCallback(() => {
    controllerRef.current?.stop();
    setScreenOpen(false);
  }, []);

  React.useEffect(() => () => controllerRef.current?.stop(), []);


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

  // A small text file is read here in the browser and its text joins the box (nothing uploads).
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be picked again
    if (!file) return;
    setAttachError(null);
    const verdict = checkAttachment(file);
    if (!verdict.ok) return setAttachError(`salesAssistant.attach.${verdict.reason}`);
    let raw;
    try {
      raw = await file.text();
    } catch {
      return setAttachError("salesAssistant.attach.read");
    }
    const merged = mergeAttachment(valueRef.current, file.name, raw);
    if (!merged.ok) return setAttachError(`salesAssistant.attach.${merged.reason}`);
    onChange(merged.text);
    ref.current?.focus();
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
      <VoiceScreen
        open={screenOpen}
        state={callState}
        message={callError ?? ""}
        meter={meterRef.current}
        note={
          micPrompt
            ? "اضغط على الشاشة لتشغيل الميكروفون"
            : micError
              ? MIC_ERROR_TEXT[micError] ?? MIC_ERROR_TEXT.mic_failed
              : audioNote || socketNote
        }
        onGesture={
          micPrompt
            ? async () => {
                const resumed = await controllerRef.current?.resumeMic();
                if (resumed) setMicPrompt(false);
              }
            : null
        }
        onClose={closeScreen}
        onInterrupt={() => controllerRef.current?.interrupt()}
      />
      {error ? (
        <p data-testid="assistant-send-error" role="alert" className="mb-2 px-3 text-center text-[12.5px] text-destructive">
          {error}
        </p>
      ) : null}
      {voiceError ? (
        <p data-testid="assistant-voice-error" role="alert" className="mb-2 px-3 text-center text-[12.5px] text-destructive">
          {t(voiceError)}
        </p>
      ) : null}
      {attachError ? (
        <p data-testid="assistant-attach-error" role="alert" className="mb-2 px-3 text-center text-[12.5px] text-destructive">
          {t(attachError)}
        </p>
      ) : null}
      <div
        data-testid="assistant-composer-field"
        className={`rounded-3xl border bg-card px-4 pb-2 pt-3 shadow-[0_4px_18px_-8px_rgba(0,0,0,0.18)] transition-all ${
          disabled
            ? "border-border opacity-70"
            : listening
              ? "border-primary/50 ring-4 ring-primary/10"
              : "border-border focus-within:border-foreground/25 focus-within:shadow-[0_6px_24px_-8px_rgba(0,0,0,0.24)]"
        }`}
      >
        {callError ? (
          <p data-testid="assistant-call-error" className="mb-1 text-[11.5px] font-medium text-destructive">
            {callError}
          </p>
        ) : null}
        {listening ? (
          <span data-testid="assistant-listening" className="mb-1 flex items-center gap-1.5 text-[11.5px] font-medium text-primary">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            {t("salesAssistant.listening")}
          </span>
        ) : null}
        <textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled}
          onChange={(e) => {
            if (attachError) setAttachError(null);
            onChange(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={t("salesAssistant.composerPlaceholder")}
          className="max-h-40 min-h-[28px] w-full resize-none bg-transparent text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
        />
        <div className="mt-1 flex items-center justify-between gap-1">
          <input
            ref={fileRef}
            type="file"
            data-testid="assistant-file-input"
            accept={ATTACH_EXTENSIONS.map((x) => `.${x}`).join(",")}
            onChange={onFile}
            className="hidden"
            tabIndex={-1}
          />
          <button
            type="button"
            data-testid="assistant-attach"
            onClick={() => fileRef.current?.click()}
            disabled={disabled}
            title={t("salesAssistant.attach.button")}
            aria-label={t("salesAssistant.attach.button")}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface hover:text-foreground disabled:opacity-40"
          >
            <Plus className="h-[18px] w-[18px]" />
          </button>
          <span className="flex items-center gap-1">
            <button
              type="button"
              data-testid="assistant-call"
              onClick={toggleCall}
              disabled={disabled}
              aria-pressed={calling}
              aria-label={calling ? t("salesAssistant.callStop") : t("salesAssistant.callStart")}
              title={calling ? t("salesAssistant.callStop") : t("salesAssistant.callStart")}
              className={`grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-40 ${
                calling ? "bg-destructive/15 text-destructive" : "text-muted-foreground hover:bg-surface hover:text-foreground"
              }`}
            >
              {calling ? <Square className="h-3.5 w-3.5 fill-current" /> : <AudioLines className="h-[18px] w-[18px]" />}
            </button>
            {calling ? (
              <button
                type="button"
                data-testid="assistant-interrupt"
                onClick={() => controllerRef.current?.interrupt()}
                aria-label={t("salesAssistant.callInterrupt")}
                title={t("salesAssistant.callInterrupt")}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
              >
                <VolumeX className="h-[18px] w-[18px]" />
              </button>
            ) : null}
            {supported ? (
              <button
                type="button"
                data-testid="assistant-mic"
                onClick={toggleMic}
                disabled={disabled}
                aria-pressed={listening}
                aria-label={listening ? t("salesAssistant.micStop") : t("salesAssistant.micStart")}
                title={listening ? t("salesAssistant.micStop") : t("salesAssistant.micStart")}
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-40 ${
                  listening ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-surface hover:text-foreground"
                }`}
              >
                {listening ? <Square className="h-3.5 w-3.5 fill-current" /> : <Mic className="h-[18px] w-[18px]" />}
              </button>
            ) : null}
            <button
              type="button"
              data-testid="assistant-send"
              onClick={submit}
              disabled={disabled || !value.trim()}
              title={t("salesAssistant.send")}
              aria-label={t("salesAssistant.send")}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm transition-all hover:opacity-90 active:scale-95 disabled:opacity-30"
            >
              <ArrowUp className="h-[18px] w-[18px]" />
            </button>
          </span>
        </div>
      </div>
      <p className="mt-2.5 px-1 text-center text-[11px] text-muted-foreground/70">
        {t("salesAssistant.composerHint")}
      </p>
    </div>
  );
}
