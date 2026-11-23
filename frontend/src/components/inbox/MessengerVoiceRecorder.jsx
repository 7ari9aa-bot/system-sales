import React, { useEffect, useRef, useState } from "react";
import { Mic, Send, Trash2 } from "lucide-react";

// Messenger's Send API plays audio/mp4 (m4a), audio/mpeg, audio/aac and audio/wav. It does not
// play ogg or webm, which is what most browsers record by default, so only mp4 is offered here.
// A browser that cannot record it says so up front instead of failing after the upload.
export const MESSENGER_RECORDING_TYPES = ["audio/mp4;codecs=mp4a.40.2", "audio/mp4"];

export function pickMessengerRecordingType(isTypeSupported) {
  for (const t of MESSENGER_RECORDING_TYPES) {
    if (isTypeSupported?.(t)) return t;
  }
  return null;
}

const WORDS = {
  ar: {
    cancel: "إلغاء التسجيل",
    send: "إيقاف وإرسال",
    recording: "جارٍ التسجيل",
    denied: "لم يُسمح باستخدام الميكروفون. اسمح به من إعدادات المتصفح.",
    none: "لم يتم العثور على ميكروفون على هذا الجهاز.",
    failed: "تعذّر بدء التسجيل. حاول مرة أخرى.",
    unsupported: "هذا المتصفح لا يسجّل بصيغة يقبلها ماسنجر (M4A). جرّب Safari أو أرسل ملفًا صوتيًا جاهزًا.",
    tooShort: "التسجيل قصير جدًا. اضغط مطولًا ثانية على الأقل.",
  },
  en: {
    cancel: "Cancel recording",
    send: "Stop and send",
    recording: "Recording",
    denied: "Microphone access was blocked. Allow it in the browser settings.",
    none: "No microphone was found on this device.",
    failed: "Could not start recording. Try again.",
    unsupported: "This browser cannot record in a format Messenger plays (M4A). Try Safari or attach an audio file.",
    tooShort: "The recording is too short. Record at least one second.",
  },
};

const MIN_SECONDS = 1;

function explain(err, w) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") return w.denied;
  if (name === "NotFoundError" || name === "OverconstrainedError") return w.none;
  return w.failed;
}

function clock(total) {
  const s = Math.max(0, Math.floor(total));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Records a voice note for Messenger and hands the finished M4A file to `onDone`; it then goes
 * through the same preview and upload as any other Messenger attachment.
 */
export default function MessengerVoiceRecorder({
  onCancel,
  onDone,
  onError,
  lang = "ar",
  accent = "#0084ff",
  mediaDevices = globalThis.navigator?.mediaDevices,
  Recorder = globalThis.MediaRecorder,
}) {
  const w = WORDS[lang] || WORDS.en;
  const [seconds, setSeconds] = useState(0);
  const [ready, setReady] = useState(false);
  const rec = useRef(null);
  const stream = useRef(null);
  const chunks = useRef([]);
  const startedAt = useRef(0);
  const cancelled = useRef(false);

  const release = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!mediaDevices?.getUserMedia || !Recorder) { onError?.(w.unsupported); onCancel?.(); return; }
      const mime = pickMessengerRecordingType((t) => Recorder.isTypeSupported?.(t));
      if (!mime) { onError?.(w.unsupported); onCancel?.(); return; }
      try {
        const s = await mediaDevices.getUserMedia({ audio: true });
        if (!alive) { s.getTracks().forEach((t) => t.stop()); return; }
        stream.current = s;
        const r = new Recorder(s, { mimeType: mime });
        r.ondataavailable = (e) => { if (e.data?.size) chunks.current.push(e.data); };
        r.onstop = () => {
          release();
          if (cancelled.current) return;
          const elapsed = (Date.now() - startedAt.current) / 1000;
          if (elapsed < MIN_SECONDS) { onError?.(w.tooShort); onCancel?.(); return; }
          const blob = new Blob(chunks.current, { type: "audio/mp4" });
          onDone?.(new File([blob], `voice-${Date.now()}.m4a`, { type: "audio/mp4" }), Math.round(elapsed));
        };
        rec.current = r;
        startedAt.current = Date.now();
        r.start();
        setReady(true);
      } catch (err) {
        if (alive) { onError?.(explain(err, w)); onCancel?.(); }
      }
    })();
    return () => {
      alive = false;
      cancelled.current = true;
      try { if (rec.current && rec.current.state !== "inactive") rec.current.stop(); } catch { /* already stopped */ }
      release();
    };
  }, []);

  useEffect(() => {
    if (!ready) return undefined;
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - startedAt.current) / 1000)), 250);
    return () => clearInterval(id);
  }, [ready]);

  const stop = () => { try { rec.current?.stop(); } catch { /* already stopped */ } };
  const cancel = () => {
    cancelled.current = true;
    try { if (rec.current?.state !== "inactive") rec.current?.stop(); } catch { /* already stopped */ }
    release();
    onCancel?.();
  };

  return (
    <div
      data-testid="messenger-voice-recorder"
      role="status"
      aria-live="polite"
      dir="ltr"
      className="flex h-9 items-center gap-2 rounded-full bg-[#f0f2f5] px-2"
    >
      <button
        type="button"
        onClick={cancel}
        aria-label={w.cancel}
        title={w.cancel}
        data-testid="messenger-voice-cancel"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#65676b] hover:bg-[#e4e6eb]"
      >
        <Trash2 className="h-4 w-4" />
      </button>
      <span className="flex flex-1 items-center gap-2 text-[14px] text-[#050505]">
        <span aria-hidden="true" className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#e41e3f]" />
        <span data-testid="messenger-voice-time" className="tabular-nums">{clock(seconds)}</span>
        <span className="text-[13px] text-[#65676b]">{w.recording}</span>
        <Mic className="h-4 w-4 text-[#65676b]" />
      </span>
      <button
        type="button"
        onClick={stop}
        disabled={!ready}
        aria-label={w.send}
        title={w.send}
        data-testid="messenger-voice-stop"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white disabled:opacity-40"
        style={{ background: accent }}
      >
        <Send className="h-4 w-4" />
      </button>
    </div>
  );
}
