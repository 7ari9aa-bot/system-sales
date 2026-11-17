import React, { useEffect, useRef, useState } from "react";
import { CloseIcon, MicIcon, SendIcon } from "./icons";
import { formatDuration, pickRecordingType } from "./attachments";

const WORDS = {
  ar: { cancel: "إلغاء التسجيل", send: "إرسال", recording: "جارٍ التسجيل", denied: "لم يُسمح باستخدام الميكروفون. اسمح به من إعدادات المتصفح.", none: "لا يوجد ميكروفون في هذا الجهاز.", unsupported: "هذا المتصفح لا يسجّل بصيغة يقبلها واتساب. جرّب Chrome أو Safari.", failed: "تعذّر بدء التسجيل.", tooShort: "التسجيل قصير جدًا." },
  en: { cancel: "Cancel recording", send: "Send", recording: "Recording", denied: "Microphone access was blocked. Allow it in the browser settings.", none: "No microphone was found on this device.", unsupported: "This browser cannot record in a format WhatsApp accepts. Try Chrome or Safari.", failed: "Could not start recording.", tooShort: "The recording is too short." },
};

const MIN_SECONDS = 1;

/** Why getUserMedia failed, in words the agent can act on. */
export function explainMicError(err, w) {
  const name = err?.name || "";
  if (name === "NotAllowedError" || name === "SecurityError") return w.denied;
  if (name === "NotFoundError" || name === "OverconstrainedError") return w.none;
  return w.failed;
}

/**
 * Records a real voice note with the browser's MediaRecorder and hands the
 * finished file to `onDone` (it then goes through the same preview and upload
 * as any other file). It records only in a format WhatsApp plays (ogg/opus or
 * mp4/aac); webm is refused up front instead of failing after the upload.
 */
export default function VoiceRecorder({ onCancel, onDone, onError, lang = "ar", mediaDevices = globalThis.navigator?.mediaDevices, Recorder = globalThis.MediaRecorder }) {
  const w = WORDS[lang] || WORDS.en;
  const [seconds, setSeconds] = useState(0);
  const [ready, setReady] = useState(false);
  const rec = useRef(null);
  const stream = useRef(null);
  const chunks = useRef([]);
  const startedAt = useRef(0);
  const cancelled = useRef(false);
  const type = useRef(null);

  const release = () => { stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null; };

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!mediaDevices?.getUserMedia || !Recorder) { onError?.(w.unsupported); onCancel?.(); return; }
      const mime = pickRecordingType((t) => Recorder.isTypeSupported?.(t));
      if (!mime) { onError?.(w.unsupported); onCancel?.(); return; }
      try {
        const s = await mediaDevices.getUserMedia({ audio: true });
        if (!alive) { s.getTracks().forEach((t) => t.stop()); return; }
        stream.current = s;
        type.current = mime;
        const r = new Recorder(s, { mimeType: mime });
        r.ondataavailable = (e) => { if (e.data?.size) chunks.current.push(e.data); };
        r.onstop = () => {
          release();
          if (cancelled.current) return;
          const elapsed = (Date.now() - startedAt.current) / 1000;
          if (elapsed < MIN_SECONDS) { onError?.(w.tooShort); onCancel?.(); return; }
          const base = mime.split(";")[0];
          const ext = base === "audio/mp4" ? "m4a" : "ogg";
          const blob = new Blob(chunks.current, { type: base });
          onDone?.(new File([blob], `voice-${Date.now()}.${ext}`, { type: base }), Math.round(elapsed));
        };
        rec.current = r;
        startedAt.current = Date.now();
        r.start();
        setReady(true);
      } catch (err) {
        if (alive) { onError?.(explainMicError(err, w)); onCancel?.(); }
      }
    })();
    return () => {
      alive = false; cancelled.current = true;
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
  const cancel = () => { cancelled.current = true; try { if (rec.current?.state !== "inactive") rec.current?.stop(); } catch { /* already stopped */ } release(); onCancel?.(); };

  return (
    <div data-testid="voice-recorder" role="status" aria-live="polite" dir="ltr" className="flex min-h-[52px] items-center gap-3 px-3 py-1.5">
      <button type="button" onClick={cancel} aria-label={w.cancel} title={w.cancel} data-testid="voice-cancel" className="grid h-10 w-10 place-items-center rounded-full text-[#54656f] hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"><CloseIcon size={22} /></button>
      <span className="flex flex-1 items-center gap-2 text-[15px] text-[#111b21]">
        <span aria-hidden="true" className="h-3 w-3 animate-pulse rounded-full bg-[#ea0038]" />
        <span data-testid="voice-time" className="tabular-nums">{formatDuration(seconds)}</span>
        <span className="text-[13px] text-[#667781]">{w.recording}</span>
        <MicIcon size={18} className="text-[#667781]" />
      </span>
      <button type="button" onClick={stop} disabled={!ready} aria-label={w.send} title={w.send} data-testid="voice-stop" className="grid h-11 w-11 place-items-center rounded-full bg-[#00a884] text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] focus-visible:ring-offset-2 disabled:opacity-50"><SendIcon size={22} className={lang === "ar" ? "-scale-x-100" : undefined} /></button>
    </div>
  );
}
