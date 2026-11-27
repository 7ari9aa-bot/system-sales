/** شاشة المكالمة: دايرة في النص، خلفية متحركة، ومفيش أي حاجة تانية تشتّت.
 *
 *  الشاشة عرض بس: الحالة والمكالمة نفسها في الكومبوزر. عشان كده بتتست من غير مايك
 *  ولا WebRTC — بنتأكد إنها بتظهر وبتنادي على الإجراءات الصح.
 */
import React from "react";

import VoiceOrb from "./orb/VoiceOrb";

const RING = "voice-ring";
const BLOB = "voice-blob";

function useElapsed(active) {
  const [seconds, setSeconds] = React.useState(0);
  React.useEffect(() => {
    if (!active) {
      setSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return seconds;
}

const FAILED_STATES = ["refused", "unavailable", "not_found", "failed", "closed"];

/** الحالة زي ما بتتعرض: النص، وهل القاطع مسموح، وهل هي حالة فشل. */
export function screenView({ state = "opening", message = "", labels = {} } = {}) {
  const fallback = state === "live" ? labels.live ?? "أنت تتحدث الآن" : labels.opening ?? "جارٍ تهيئة الميكروفون…";
  return {
    text: message || fallback,
    failed: FAILED_STATES.includes(state),
    canInterrupt: state === "live",
  };
}

export function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export default function VoiceScreen({
  open,
  state = "opening",
  message = "",
  interrupted = false,
  note = "",
  onGesture = null,
  onClose = () => {},
  onInterrupt = () => {},
  labels = {},
  meter = null,
}) {
  const elapsed = useElapsed(open && state === "live");
  const view = screenView({ state, message, labels });

  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;


  return (
    <div
      data-testid="voice-screen"
      onClick={onGesture ?? undefined}
      dir="rtl"
      className="fixed inset-0 z-[80] flex flex-col items-center justify-center overflow-hidden bg-[#05070d] text-white"
    >
      <style>{`
        @keyframes ${RING} { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        @keyframes ${BLOB} {
          0% { transform: translate3d(0,0,0) scale(1); }
          50% { transform: translate3d(6%, -8%, 0) scale(1.15); }
          100% { transform: translate3d(0,0,0) scale(1); }
        }
        @keyframes voice-breathe {
          0%, 100% { transform: scale(1); opacity: .85; }
          50% { transform: scale(1.06); opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          .voice-ring, .voice-blob, .voice-core { animation: none !important; }
        }
      `}</style>

      {/* خلفية متحركة: ثلاث بقع ضوء بتدور ببطء ورا الدايرة */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div
          className={`${BLOB} voice-blob absolute -top-1/3 right-[-10%] h-[70vh] w-[70vh] rounded-full bg-emerald-500/25 blur-[120px]`}
          style={{ animation: `${BLOB} 18s ease-in-out infinite` }}
        />
        <div
          className={`${BLOB} voice-blob absolute bottom-[-25%] left-[-15%] h-[65vh] w-[65vh] rounded-full bg-indigo-500/25 blur-[130px]`}
          style={{ animation: `${BLOB} 24s ease-in-out infinite reverse` }}
        />
        <div
          className={`${BLOB} voice-blob absolute left-1/3 top-1/4 h-[45vh] w-[45vh] rounded-full bg-sky-400/20 blur-[110px]`}
          style={{ animation: `${BLOB} 30s ease-in-out infinite` }}
        />
      </div>

      <div className="relative flex flex-1 flex-col items-center justify-center gap-8 px-6">
        <VoiceOrb
          state={state}
          meter={meter}
          className="h-64 w-64 sm:h-72 sm:w-72"
        />

        <div className="text-center">
          <p data-testid="voice-screen-state" className="text-lg font-semibold">
            {view.text}
          </p>
          <p data-testid="voice-screen-timer" className="mt-1 font-mono text-sm text-white/60">
            {formatElapsed(elapsed)}
          </p>
          {note ? (
            <p data-testid="voice-screen-note" className="mt-2 font-mono text-[11px] text-white/40">
              {note}
            </p>
          ) : null}
        </div>
      </div>

      <div className="relative mb-10 flex items-center gap-4">
        <button
          type="button"
          data-testid="voice-screen-interrupt"
          onClick={onInterrupt}
          disabled={!view.canInterrupt}
          className="rounded-full border border-white/15 bg-white/10 px-5 py-3 text-sm font-medium text-white/90 backdrop-blur transition hover:bg-white/20 disabled:opacity-40"
        >
          {interrupted ? "تم إسكات المساعد" : "مقاطعة"}
        </button>
        <button
          type="button"
          data-testid="voice-screen-close"
          onClick={onClose}
          aria-label="إنهاء المكالمة"
          className="grid h-14 w-14 place-items-center rounded-full bg-red-500 text-white shadow-lg shadow-red-500/30 transition hover:bg-red-600"
        >
          <span className="text-xl" aria-hidden>
            ✕
          </span>
        </button>
      </div>
    </div>
  );
}
