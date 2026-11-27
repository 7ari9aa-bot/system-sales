/** جلسة الصوت في المتصفح: نطلب توكن من الـcontrol plane، ندخل غرفة LiveKit، نفتح
 *  المايك، ونقفل كل حاجة في الآخر.
 *
 *  التوكن عمره 60 ثانية وبيخص جلسة واحدة بس، فمفيش أي سر بيوصل للمتصفح غير توكن
 *  بيموت. والغرفة اسمها id الجلسة، مش اسم المتجر ولا الـtenant.
 *
 *  `roomFactory` و`apiFn` بيتحقنوا عشان الكود كله يتست من غير شبكة ولا WebRTC حقيقي.
 */
import { api } from "../lib/api";

export const VOICE_STATE = {
  IDLE: "idle",
  REQUESTING: "requesting",
  CONNECTING: "connecting",
  LIVE: "live",
  REFUSED: "refused",
  UNAVAILABLE: "unavailable",
  NOT_FOUND: "not_found",
  FAILED: "failed",
  CLOSED: "closed",
};

/** رسالة لكل رفض، بالمصري، بتقول للمستخدم يعمل إيه بدل ما تسيب الشاشة ساكتة. */
const MESSAGES = {
  [VOICE_STATE.REFUSED]: "هذه الجلسة لا تدعم الصوت المباشر حالياً.",
  [VOICE_STATE.UNAVAILABLE]: "خدمة الصوت غير متاحة حالياً، يرجى المحاولة بعد قليل.",
  [VOICE_STATE.NOT_FOUND]: "الجلسة غير موجودة أو لا تخص حسابك.",
  [VOICE_STATE.FAILED]: "تعذّر فتح الميكروفون أو الاتصال بالغرفة.",
  [VOICE_STATE.CLOSED]: "تم إنهاء المكالمة.",
};

export function describeState(state) {
  return MESSAGES[state] ?? "";
}

/** الحالات اللي السيرفر بيرفضها برسالة واضحة، وكل واحدة ليها معنى مختلف. */
export function stateForStatus(status) {
  if (status === 409) return VOICE_STATE.REFUSED;
  if (status === 404) return VOICE_STATE.NOT_FOUND;
  if (status === 503) return VOICE_STATE.UNAVAILABLE;
  return VOICE_STATE.FAILED;
}

async function defaultRoomFactory() {
  const { Room } = await import("livekit-client");
  return new Room();
}

/** نطلب التوكن من الـcontrol plane. الغرفة والتوكن هما كل اللي بنحتاجهم. */
export async function requestTransport(sessionId, { apiFn = api } = {}) {
  try {
    const credential = await apiFn(`/voice/sessions/${sessionId}/transport`, {
      method: "POST",
    });
    if (!credential?.url || !credential?.token) {
      return { ok: false, state: VOICE_STATE.FAILED, message: describeState(VOICE_STATE.FAILED) };
    }
    return { ok: true, credential };
  } catch (error) {
    const status = error?.status ?? error?.response?.status;
    const state = stateForStatus(status);
    return { ok: false, state, message: describeState(state) };
  }
}

/**
 * تفتح مكالمة: توكن، دخول الغرفة، مايك. وبترجّع `stop` بتقفل الاتنين حتى لو حاجة فشلت.
 */
export async function startVoiceSession({
  sessionId,
  roomFactory = defaultRoomFactory,
  apiFn = api,
  onState = () => {},
} = {}) {
  onState(VOICE_STATE.REQUESTING);
  const transport = await requestTransport(sessionId, { apiFn });
  if (!transport.ok) {
    onState(transport.state);
    return { ok: false, state: transport.state, message: transport.message, stop: async () => {} };
  }

  const { credential } = transport;
  let room = null;
  try {
    room = await roomFactory();
    onState(VOICE_STATE.CONNECTING);
    await room.connect(credential.url, credential.token);
    await room.localParticipant.setMicrophoneEnabled(true);
    onState(VOICE_STATE.LIVE);
  } catch (error) {
    if (room) {
      await room.disconnect().catch(() => {});
    }
    onState(VOICE_STATE.FAILED);
    return {
      ok: false,
      state: VOICE_STATE.FAILED,
      message: describeState(VOICE_STATE.FAILED),
      stop: async () => {},
    };
  }

  return {
    ok: true,
    state: VOICE_STATE.LIVE,
    credential,
    room,
    stop: async () => {
      await room.disconnect().catch(() => {});
      onState(VOICE_STATE.CLOSED);
    },
  };
}
