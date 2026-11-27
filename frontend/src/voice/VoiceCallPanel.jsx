/** زر المكالمة الصوتية للمساعد. بيقول الحالة بالعربي وبيوقف المايك لما تقفل. */
import { VOICE_STATE } from "./session";
import { useVoiceSession } from "./useVoiceSession";

/** نص الزر من الحالة — دالة نقية عشان تتست من غير DOM. */
export function buttonLabel(state) {
  if (state === VOICE_STATE.LIVE) return "اقفل المكالمة";
  if (state === VOICE_STATE.REQUESTING || state === VOICE_STATE.CONNECTING) return "بيفتح...";
  return "ابدأ المكالمة";
}

export default function VoiceCallPanel({ sessionId }) {
  const { state, message, isLive, isBusy, start, stop } = useVoiceSession({ sessionId });

  return (
    <div className="rounded-lg border p-4" data-testid="voice-call-panel" data-state={state}>
      <p className="text-sm font-medium">المساعد الصوتي</p>
      {message ? (
        <p className="mt-1 text-xs text-muted-foreground" data-testid="voice-call-message">
          {message}
        </p>
      ) : null}
      <button
        type="button"
        className="mt-3 rounded-md border px-3 py-1.5 text-sm"
        data-testid="voice-call-toggle"
        disabled={isBusy}
        onClick={isLive ? stop : start}
      >
        {buttonLabel(state)}
      </button>
    </div>
  );
}
