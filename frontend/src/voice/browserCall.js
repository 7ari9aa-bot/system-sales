/** مكالمة صوت حقيقية من المتصفح: صوتك PCM رايح للسيرفر، وصوت المساعد راجع يتشغّل.
 *
 *  المتصفح ماسكش مفتاح الـgateway: السيرفر هو اللي فاتح سوكت GPT-Live، والمتصفح بياخد
 *  تذكرة عمرها 60 ثانية لجلسة واحدة بس. التذكرة بتتحوّل مرة واحدة، فحتى لو اتسربت مش
 *  هتفتح حاجة بعد ما الصفحة تتصل.
 *
 *  كل حاجة خارجية (fetch، WebSocket، المايك، السمّاعة) بتتحقن، فالمسار كله بيتست من غير
 *  شبكة ولا مايك حقيقي.
 */
import { api, apiUrl } from "../lib/api";

export const STREAM_STATE = {
  IDLE: "idle",
  OPENING: "opening",
  LIVE: "live",
  REFUSED: "refused",
  UNAVAILABLE: "unavailable",
  NOT_FOUND: "not_found",
  FAILED: "failed",
  CLOSED: "closed",
};

const MESSAGES = {
  [STREAM_STATE.OPENING]: "بجهّز المايك…",
  [STREAM_STATE.LIVE]: "بتتكلم دلوقتي",
  [STREAM_STATE.REFUSED]: "الجلسة دي مش بتاخد صوت مباشر دلوقتي.",
  [STREAM_STATE.UNAVAILABLE]: "خدمة الصوت مش متاحة حالياً، جرّب تاني بعد شوية.",
  [STREAM_STATE.NOT_FOUND]: "الجلسة مش موجودة أو مش بتاعتك.",
  [STREAM_STATE.FAILED]: "تعذّر فتح المايك أو الاتصال.",
  [STREAM_STATE.CLOSED]: "المكالمة اتقفلت.",
};

export function describeStreamState(state) {
  return MESSAGES[state] ?? "";
}

/** الحالات اللي السيرفر بيرفضها، وكل واحدة ليها معنى مختلف عن التانية. */
export function streamStateForStatus(status) {
  if (status === 409) return STREAM_STATE.REFUSED;
  if (status === 404) return STREAM_STATE.NOT_FOUND;
  if (status === 503) return STREAM_STATE.UNAVAILABLE;
  return STREAM_STATE.FAILED;
}

/** close codes من الـwebsocket: 1008 رفض صلاحية، 1011 الرانتايم مش مظبّط. */
export function streamStateForClose(code) {
  if (code === 1008) return STREAM_STATE.REFUSED;
  if (code === 1011) return STREAM_STATE.UNAVAILABLE;
  return STREAM_STATE.CLOSED;
}

/** نفس أصل الـAPI بس بـws/wss، عشان السوكت يروح لنفس السيرفر. */
export function websocketUrl(path, apiUrlFn = apiUrl) {
  const absolute = apiUrlFn(path);
  if (typeof absolute === "string" && /^https?:\/\//.test(absolute)) {
    return absolute.replace(/^http/, "ws");
  }
  if (typeof window === "undefined" || !window.location) return absolute;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${absolute}`;
}

/** PCM16 نضيف من float، مع قص القيم اللي برة المدى بدل ما تلفّ وتعمل ضوضاء. */
export function floatToPcm16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

/** الـgateway بياخد 24kHz؛ لو الـAudioContext شغال على 48k بنعمل decimation بسيط. */
export function resampleTo(samples, fromRate, toRate = 24000) {
  if (!fromRate || fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const length = Math.floor(samples.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    out[i] = samples[Math.floor(i * ratio)];
  }
  return out;
}

/** جلسة صوت جديدة بنفس الـclient_key ترجع نفس الجلسة بدل ما تفتح مكالمة تانية مدفوعة. */
export async function openVoiceSession({ apiFn = api, clientKey } = {}) {
  const key = clientKey ?? (typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `tab-${Date.now()}`);
  const session = await apiFn("/voice/sessions", {
    method: "POST",
    body: { channel: "web_voice", client_key: key },
  });
  return session?.id ?? null;
}

async function defaultWsFactory(url) {
  return new WebSocket(url);
}

/** المايك الحقيقي: worklet بيسيب 100ms كل مرة، ولو مش مدعوم بنرجع لـScriptProcessor. */
export function createMicSource({ win = typeof window !== "undefined" ? window : undefined } = {}) {
  let context = null;
  let stream = null;
  let node = null;

  async function start(onChunk) {
    if (!win?.navigator?.mediaDevices?.getUserMedia) throw new Error("no microphone");
    stream = await win.navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const Ctx = win.AudioContext || win.webkitAudioContext;
    context = new Ctx();
    const source = context.createMediaStreamSource(stream);
    const rate = context.sampleRate;
    const chunkSamples = Math.floor(rate / 10); // 100ms
    let buffer = new Float32Array(chunkSamples);
    let filled = 0;

    const flush = (samples) => {
      const pcm = floatToPcm16(resampleTo(samples, rate, 24000));
      onChunk(pcm.buffer);
    };

    // ScriptProcessor أوسع دعم من worklet ومفيش ملف إضافي، والـ100ms تأخير مقبول.
    node = context.createScriptProcessor(2048, 1, 1);
    node.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      for (let i = 0; i < input.length; i += 1) {
        buffer[filled] = input[i];
        filled += 1;
        if (filled === chunkSamples) {
          flush(buffer);
          filled = 0;
        }
      }
    };
    source.connect(node);
    node.connect(context.destination);
  }

  function stop() {
    try {
      if (node) node.disconnect();
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (context) context.close();
    } finally {
      node = null;
      stream = null;
      context = null;
    }
  }

  return { start, stop };
}

/** السمّاعة: كل دلتا PCM16 24k بتتحوّل AudioBuffer وتتجدول ورا بعضها. */
export function createPcmPlayer({ win = typeof window !== "undefined" ? window : undefined } = {}) {
  let context = null;
  let playhead = 0;

  function ensure() {
    if (!context) {
      const Ctx = win.AudioContext || win.webkitAudioContext;
      context = new Ctx();
      playhead = context.currentTime;
    }
    return context;
  }

  function play(arrayBuffer) {
    const ctx = ensure();
    const pcm = new Int16Array(arrayBuffer);
    if (!pcm.length) return;
    const floats = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i += 1) floats[i] = pcm[i] / 0x8000;
    const buffer = ctx.createBuffer(1, floats.length, 24000);
    buffer.copyToChannel(floats, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(playhead, ctx.currentTime);
    source.start(startAt);
    playhead = startAt + buffer.duration;
  }

  function stop() {
    if (context) {
      context.close();
      context = null;
    }
    playhead = 0;
  }

  return { play, stop };
}

/** تذكرة الستريم: 60 ثانية، جلسة واحدة، وتتحوّل مرة واحدة على السيرفر. */
export async function requestStreamTicket(sessionId, { apiFn = api } = {}) {
  const ticket = await apiFn(`/voice/sessions/${sessionId}/stream-ticket`, { method: "POST" });
  if (!ticket?.ticket || !ticket?.path) return null;
  return ticket;
}

/** مكالمة واحدة من أولها لآخرها. بيرجّع handle فيه stop() والحالة الحالية. */
export async function startBrowserCall({
  sessionId,
  apiFn = api,
  wsFactory = defaultWsFactory,
  micFactory = createMicSource,
  playerFactory = createPcmPlayer,
  onState = () => {},
} = {}) {
  const state = { value: STREAM_STATE.IDLE };
  const setState = (next) => {
    state.value = next;
    onState(next, describeStreamState(next));
  };

  if (!sessionId) {
    setState(STREAM_STATE.NOT_FOUND);
    return { stop: () => {}, interrupt: () => {}, get state() { return state.value; } };
  }

  setState(STREAM_STATE.OPENING);
  let ticket;
  try {
    ticket = await requestStreamTicket(sessionId, { apiFn });
  } catch (error) {
    setState(streamStateForStatus(error?.status ?? error?.response?.status));
    return { stop: () => {}, interrupt: () => {}, get state() { return state.value; } };
  }
  if (!ticket) {
    setState(STREAM_STATE.UNAVAILABLE);
    return { stop: () => {}, interrupt: () => {}, get state() { return state.value; } };
  }

  const mic = micFactory();
  const player = playerFactory();
  let socket = null;
  let stopped = false;

  const cleanup = () => {
    if (stopped) return;
    stopped = true;
    try {
      mic.stop();
    } catch {
      /* المايك بيتقفل حتى لو فشل */
    }
    try {
      player.stop();
    } catch {
      /* نفس الحكاية للسمّاعة */
    }
    try {
      if (socket && socket.readyState === 1) socket.close(1000);
    } catch {
      /* القفل مش هيفشل المكالمة */
    }
  };

  try {
    socket = await wsFactory(`${websocketUrl(ticket.path)}?ticket=${encodeURIComponent(ticket.ticket)}`);
  } catch {
    setState(STREAM_STATE.FAILED);
    cleanup();
    return { stop: cleanup, get state() { return state.value; } };
  }

  socket.binaryType = "arraybuffer";
  socket.onmessage = (event) => {
    if (event?.data instanceof ArrayBuffer) player.play(event.data);
  };
  socket.onclose = (event) => {
    cleanup();
    setState(streamStateForClose(event?.code));
  };

  try {
    await mic.start((chunk) => {
      if (socket.readyState === 1) socket.send(chunk);
    });
  } catch {
    setState(STREAM_STATE.FAILED);
    cleanup();
    return { stop: cleanup, get state() { return state.value; } };
  }

  setState(STREAM_STATE.LIVE);
  return {
    stop: () => {
      cleanup();
      setState(STREAM_STATE.CLOSED);
    },
    interrupt: () => {
      // Barge-in: silence the speaker now, and tell the server to drop the rest
      // of the model's turn. The call stays open — the caller is still talking.
      try {
        player.stop();
      } catch {
        /* الصوت بيتوقف حتى لو حصل خطأ */
      }
      try {
        if (socket && socket.readyState === 1) {
          socket.send(JSON.stringify({ type: "interrupt" }));
        }
      } catch {
        /* لو الإرسال فشل، المكالمة مكمّلة زي ما هي */
      }
    },
    get state() {
      return state.value;
    },
  };
}
