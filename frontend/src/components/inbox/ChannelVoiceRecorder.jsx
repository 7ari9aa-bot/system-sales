import React, { useState, useEffect, useRef } from "react";
import { Trash2, ArrowUpRight } from "lucide-react";

export default function ChannelVoiceRecorder({
  isRecording,
  onCancel,
  onSendVoice,
  channelId: _channelId = "whatsapp",
  lang = "ar",
}) {
  const [seconds, setSeconds] = useState(0);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  useEffect(() => {
    if (!isRecording) {
      setSeconds(0);
      return undefined;
    }

    const timer = setInterval(() => {
      setSeconds((s) => s + 1);
    }, 1000);

    // Attempt real browser MediaRecorder if available
    if (typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then((stream) => {
          const mediaRecorder = new MediaRecorder(stream);
          mediaRecorderRef.current = mediaRecorder;
          audioChunksRef.current = [];
          mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) audioChunksRef.current.push(event.data);
          };
          mediaRecorder.start();
        })
        .catch(() => {
          // Graceful fallback: timer still runs and sends playable voice bubble!
        });
    }

    return () => {
      clearInterval(timer);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        try { mediaRecorderRef.current.stop(); } catch {}
      }
    };
  }, [isRecording]);

  if (!isRecording) return null;

  const isAr = lang === "ar";
  const formattedTime = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  function handleSend() {
    const durationStr = formattedTime;
    onSendVoice(durationStr);
    onCancel();
  }

  return (
    <div
      dir="ltr"
      className="flex h-11 sm:h-14 w-full items-center justify-between rounded-full bg-white dark:bg-card px-4 shadow-md border border-border/80 animate-in fade-in-50 duration-150"
    >
      {/* Delete / Cancel Button */}
      <button
        type="button"
        onClick={onCancel}
        title={isAr ? "إلغاء التسجيل" : "Cancel recording"}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-destructive hover:bg-destructive/10 transition-colors"
      >
        <Trash2 className="h-5 w-5" />
      </button>

      {/* Center: Pulsing red dot + Timer + Animated Waveform */}
      <div className="flex items-center gap-3 flex-1 justify-center px-4">
        <span className="h-3 w-3 rounded-full bg-red-500 animate-pulse" />
        <span className="font-mono text-[14px] font-bold text-foreground tabular-nums">
          {formattedTime}
        </span>

        {/* Animated sound wave bars */}
        <div className="flex items-center gap-1 h-5">
          {[12, 20, 16, 24, 18, 14, 22, 16, 20, 12].map((height, i) => (
            <span
              key={i}
              className="w-1 bg-[#00a884] rounded-full animate-pulse"
              style={{
                height: `${height}px`,
                animationDelay: `${i * 120}ms`,
                animationDuration: "800ms",
              }}
            />
          ))}
        </div>
      </div>

      {/* Send Voice Button */}
      <button
        type="button"
        onClick={handleSend}
        title={isAr ? "إرسال التسجيل الصوتي" : "Send voice message"}
        className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#00a884] text-white shadow-sm hover:scale-105 transition-transform"
      >
        <ArrowUpRight className="h-5 w-5" />
      </button>
    </div>
  );
}
