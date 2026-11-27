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

export function createCallController({
  openSession,
  startCall,
  resetSession = null,
  onChange = () => {},
  onEnd = () => {},
}) {
  let handle = null;
  let calling = false;
  let lastError = null;
  let lastState = STREAM_STATE.IDLE;

  const publish = (next, error = null) => {
    calling = next;
    // الرفض بيتبلّغ مرة واحدة ويقعد معروض؛ مفيش تصفير بعده يخفيه.
    if (error) lastError = error;
    onChange({ calling, error: error ?? lastError, state: lastState });
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
    const onState = (state, message) => {
      lastState = state;
      if (state === STREAM_STATE.LIVE) {
        publish(true);
        return;
      }
      if (ENDED.has(state)) {
        handle = null;
        publish(false, state === STREAM_STATE.CLOSED ? null : message);
        onEnd();
      }
    };
    const begin = async () => {
      const sessionId = await openSession();
      return startCall({ sessionId, onState });
    };
    let call;
    try {
      call = await begin();
      // الجلسة المحفوظة بقت مش موجودة (متجر تاني، أو جلسة اتقفلت من زمان): بنرميها
      // وبنفتح جلسة جديدة مرة واحدة بدل ما نعرض رسالة والزر مايشتغلش خالص.
      if (call?.state === STREAM_STATE.NOT_FOUND && resetSession) {
        await resetSession();
        call = await begin();
      }
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
    /** بارج-إن: العميل بيتكلم فوق المساعد. المكالمة بتفضل مفتوحة. */
    interrupt() {
      if (!handle?.interrupt) return false;
      handle.interrupt();
      return true;
    },
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
