/** هوك المكالمة: بيدير حالة واحدة بس (idle/live/...) وبيمسك الـstop في ref عشان
 *  الخروج من الشاشة يقفل المايك من غير ما يسيب غرفة مفتوحة. */
import { useCallback, useEffect, useRef, useState } from "react";

import { VOICE_STATE, describeState, startVoiceSession } from "./session";

export function useVoiceSession({ sessionId, startFn = startVoiceSession } = {}) {
  const [state, setState] = useState(VOICE_STATE.IDLE);
  const stopRef = useRef(null);

  useEffect(
    () => () => {
      stopRef.current?.();
      stopRef.current = null;
    },
    [],
  );

  const start = useCallback(async () => {
    if (stopRef.current) return;
    const session = await startFn({ sessionId, onState: setState });
    if (session.ok) stopRef.current = session.stop;
  }, [sessionId, startFn]);

  const stop = useCallback(async () => {
    const stopNow = stopRef.current;
    stopRef.current = null;
    if (stopNow) await stopNow();
  }, []);

  return {
    state,
    message: describeState(state),
    isLive: state === VOICE_STATE.LIVE,
    isBusy: state === VOICE_STATE.REQUESTING || state === VOICE_STATE.CONNECTING,
    start,
    stop,
  };
}
