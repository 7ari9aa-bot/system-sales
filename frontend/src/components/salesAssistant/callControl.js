/** حالة زر المكالمة في الكومبوزر، من غير React — عشان تتست لوحدها.
 *
 *  الزر بيعمل حاجة واحدة: يفتح جلسة صوت ويبدأ المكالمة، أو يقفلها. الرفض من السيرفر
 *  بيظهر كرسالة، والزر بيرجع مش شغّال — مفيش حالة "متصل" كدابة.
 */
import { STREAM_STATE } from "../../voice/browserCall";

const ENDED = new Set([
  STREAM_STATE.REFUSED,
  STREAM_STATE.UNAVAILABLE,
  STREAM_STATE.NOT_FOUND,
  STREAM_STATE.FAILED,
  STREAM_STATE.CLOSED,
]);

export function createCallController({ openSession, startCall, onChange = () => {}, onEnd = () => {} }) {
  let handle = null;
  let calling = false;
  let lastError = null;

  const publish = (next, error = null) => {
    calling = next;
    // الرفض بيتبلّغ مرة واحدة ويقعد معروض؛ مفيش تصفير بعده يخفيه.
    if (error) lastError = error;
    onChange({ calling, error: error ?? lastError });
  };

  async function toggle() {
    if (handle) {
      handle.stop();
      handle = null;
      publish(false);
      onEnd();
      return;
    }
    publish(true);
    let call;
    try {
      const sessionId = await openSession();
      call = await startCall({
        sessionId,
        onState: (state, message) => {
          if (state === STREAM_STATE.LIVE) {
            publish(true);
            return;
          }
          if (ENDED.has(state)) {
            handle = null;
            publish(false, state === STREAM_STATE.CLOSED ? null : message);
            onEnd();
          }
        },
      });
    } catch {
      publish(false, "تعذّر بدء المكالمة، جرّب تاني.");
      return;
    }
    if (call?.state === STREAM_STATE.LIVE) {
      handle = call;
      return;
    }
    // السيرفر رفض قبل ما الصوت يبدأ: مفيش handle يتقفل، بس الزر مش شغّال.
    call?.stop?.();
    handle = null;
    if (!lastError) publish(false);
  }

  return {
    toggle,
    stop() {
      handle?.stop();
      handle = null;
      calling = false;
    },
    get calling() {
      return calling;
    },
  };
}
