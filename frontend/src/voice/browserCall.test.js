import { describe, expect, it, vi } from "vitest";
import {
  MIC_ERROR_TEXT,
  STREAM_STATE,
  createMicSource,
  openVoiceSession,
  describeStreamState,
  floatToPcm16,
  resampleTo,
  startBrowserCall,
  streamStateForClose,
  streamStateForStatus,
  websocketUrl,
  VOICE_WS_ORIGIN,
} from "./browserCall";

const SESSION = "11111111-1111-1111-1111-111111111111";

function fakeSocket() {
  const socket = {
    readyState: 1,
    sent: [],
    binaryType: "blob",
    closed: [],
    send: vi.fn(function send(chunk) {
      socket.sent.push(chunk);
    }),
    close: vi.fn(function close(code) {
      socket.closed.push(code);
      socket.readyState = 3;
    }),
    onmessage: null,
    onclose: null,
  };
  return socket;
}

function fakeMic() {
  const mic = {
    start: vi.fn(async (onChunk) => {
      mic.onChunk = onChunk;
    }),
    stop: vi.fn(),
  };
  return mic;
}

function fakePlayer() {
  return { play: vi.fn(), stop: vi.fn() };
}

const ticketOk = async () => ({ ticket: "the-ticket", path: `/api/v1/voice/sessions/${SESSION}/stream` });

describe("browserCall helpers", () => {
  it("maps each server refusal to its own state", () => {
    expect(streamStateForStatus(409)).toBe(STREAM_STATE.REFUSED);
    expect(streamStateForStatus(404)).toBe(STREAM_STATE.NOT_FOUND);
    expect(streamStateForStatus(503)).toBe(STREAM_STATE.UNAVAILABLE);
    expect(streamStateForStatus(500)).toBe(STREAM_STATE.FAILED);
    expect(streamStateForClose(1008)).toBe(STREAM_STATE.REFUSED);
    expect(streamStateForClose(1011)).toBe(STREAM_STATE.UNAVAILABLE);
    expect(streamStateForClose(1000)).toBe(STREAM_STATE.CLOSED);
    expect(describeStreamState(STREAM_STATE.REFUSED)).toContain("الصوت المباشر");
  });

  it("talks to the same origin as the API, over ws", () => {
    expect(websocketUrl("/api/v1/voice/sessions/x/stream", () => "https://api.example.com/api/v1/voice/sessions/x/stream"))
      .toBe("wss://api.example.com/api/v1/voice/sessions/x/stream");
  });

  it("opens the socket on the API host, because the site proxy drops the upgrade", () => {
    // الـAPI بيرجّع مسار نسبي على الإنتاج، والواجهة بتوكّله HTTP. الـwebsocket لازم يقابل
    // الـAPI نفسه وإلا الطلب يرجع 404 عادي (اللي حصل فعلاً على fihrist.world).
    expect(websocketUrl("/api/v1/voice/sessions/x/stream", (p) => p, "wss://api.example.com"))
      .toBe("wss://api.example.com/api/v1/voice/sessions/x/stream");
    expect(VOICE_WS_ORIGIN.startsWith("wss://")).toBe(true);
    expect(VOICE_WS_ORIGIN.endsWith("/")).toBe(false);
  });

  it("clamps instead of wrapping when a sample is out of range", () => {
    const pcm = floatToPcm16(new Float32Array([0, 1, -1, 2, -2]));
    expect(pcm[0]).toBe(0);
    expect(pcm[1]).toBe(32767);
    expect(pcm[2]).toBe(-32768);
    expect(pcm[3]).toBe(32767);
    expect(pcm[4]).toBe(-32768);
  });

  it("takes a 48k buffer down to 24k", () => {
    const input = new Float32Array(4800);
    expect(resampleTo(input, 48000, 24000)).toHaveLength(2400);
    expect(resampleTo(input, 24000, 24000)).toBe(input);
  });
});

describe("openVoiceSession", () => {
  it("sends the caller's client key so a re-press resumes the same session", async () => {
    const apiFn = vi.fn(async () => ({ session_id: "sess-9" }));

    const id = await openVoiceSession({ apiFn, clientKey: "screen-key" });

    expect(id).toBe("sess-9");
    expect(apiFn.mock.calls[0][0]).toBe("/voice/sessions");
    expect(apiFn.mock.calls[0][1].body).toEqual({ channel: "web_voice", client_key: "screen-key" });
  });

  it("names the open conversation so the call joins it instead of opening a second one", async () => {
    const apiFn = vi.fn(async () => ({ session_id: "sess-11" }));

    await openVoiceSession({ apiFn, clientKey: "screen-key", threadId: "thread-7" });

    // نفس المحادثة اللي بيتكتب فيها: الكلام مايبدأش محادثة جديدة
    expect(apiFn.mock.calls[0][1].body).toEqual({
      channel: "web_voice",
      client_key: "screen-key",
      thread_id: "thread-7",
    });
  });

  it("sends no thread field when the screen has no conversation yet", async () => {
    const apiFn = vi.fn(async () => ({ session_id: "sess-12" }));

    await openVoiceSession({ apiFn, clientKey: "screen-key", threadId: null });

    expect(apiFn.mock.calls[0][1].body).toEqual({ channel: "web_voice", client_key: "screen-key" });
  });

  it("still opens a session when no key is supplied", async () => {
    const apiFn = vi.fn(async () => ({ id: "sess-10" }));

    await openVoiceSession({ apiFn });

    expect(apiFn.mock.calls[0][1].body.client_key).toBeTruthy();
  });
});

describe("startBrowserCall", () => {
  it("interrupt stops the speaker and tells the server, without ending the call", async () => {
    const socket = fakeSocket();
    const mic = fakeMic();
    const player = fakePlayer();

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => mic,
      playerFactory: () => player,
    });

    call.interrupt();

    // The speaker goes quiet immediately, and the frame the server reads as
    // barge-in is a text control frame, never audio.
    expect(player.stop).toHaveBeenCalledTimes(1);
    expect(socket.sent).toContain(JSON.stringify({ type: "interrupt" }));
    expect(socket.close).not.toHaveBeenCalled();
    expect(mic.stop).not.toHaveBeenCalled();
  });

  it("a call that never opened ignores an interrupt instead of throwing", async () => {
    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: async () => {
        throw Object.assign(new Error("nope"), { status: 503 });
      },
      wsFactory: async () => fakeSocket(),
      micFactory: () => fakeMic(),
      playerFactory: () => fakePlayer(),
    });

    expect(() => call.interrupt()).not.toThrow();
  });

  it("sends mic audio and plays what comes back, then closes everything once", async () => {
    const socket = fakeSocket();
    const mic = fakeMic();
    const player = fakePlayer();
    const states = [];

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => mic,
      playerFactory: () => player,
      onState: (state) => states.push(state),
    });

    expect(states).toEqual([STREAM_STATE.OPENING, STREAM_STATE.LIVE]);

    mic.onChunk(new ArrayBuffer(8));
    expect(socket.sent).toHaveLength(1);

    const audio = new ArrayBuffer(16);
    socket.onmessage({ data: audio });
    expect(player.play).toHaveBeenCalledWith(audio);

    call.stop();
    call.stop();

    expect(mic.stop).toHaveBeenCalledTimes(1);
    expect(player.stop).toHaveBeenCalledTimes(1);
    expect(socket.closed).toEqual([1000]);
  });

  it("never opens the socket when the ticket is refused", async () => {
    const wsFactory = vi.fn();
    const micFactory = vi.fn();
    const states = [];
    const refused = Object.assign(new Error("refused"), { status: 409 });

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: async () => {
        throw refused;
      },
      wsFactory,
      micFactory,
      onState: (state) => states.push(state),
    });

    expect(call.state).toBe(STREAM_STATE.REFUSED);
    expect(wsFactory).not.toHaveBeenCalled();
    expect(micFactory).not.toHaveBeenCalled();
    expect(states.at(-1)).toBe(STREAM_STATE.REFUSED);
  });

  it("stops the mic when the server closes the socket with 1008", async () => {
    const socket = fakeSocket();
    const mic = fakeMic();
    const player = fakePlayer();
    const states = [];

    await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => mic,
      playerFactory: () => player,
      onState: (state) => states.push(state),
    });

    socket.onclose({ code: 1008 });

    expect(mic.stop).toHaveBeenCalledTimes(1);
    expect(player.stop).toHaveBeenCalledTimes(1);
    expect(states.at(-1)).toBe(STREAM_STATE.REFUSED);
  });

  it("never opens the voice socket when the mic is refused", async () => {
    // الشاشة كانت بتوصل "قناة الصوت: متصلة" والمايك لسه معلّق على نافذة الإذن، فالعميل بيدفع
    // جلسة صوتية لشخص مستحيل يسمعه. الترتيب بقى المايك الأول: مفيش مايك = مفيش سوكت خالص.
    const socket = fakeSocket();
    const wsFactory = vi.fn(async () => socket);
    const mic = {
      start: vi.fn(async () => {
        throw new Error("no microphone");
      }),
      stop: vi.fn(),
    };
    const player = fakePlayer();
    const onMicError = vi.fn();

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory,
      micFactory: () => mic,
      playerFactory: () => player,
      onMicError,
    });

    expect(call.state).toBe(STREAM_STATE.FAILED);
    expect(wsFactory).not.toHaveBeenCalled();
    expect(socket.closed).toEqual([]);
    expect(mic.stop).toHaveBeenCalledTimes(1);
    expect(onMicError).toHaveBeenCalledWith({ code: "mic_failed" });
  });

  it("starts the mic before it dials, so a granted mic still opens the call", async () => {
    const order = [];
    const socket = fakeSocket();
    const mic = {
      start: vi.fn(async () => {
        order.push("mic");
      }),
      stop: vi.fn(),
      isSuspended: () => false,
    };

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => {
        order.push("socket");
        return socket;
      },
      micFactory: () => mic,
      playerFactory: () => fakePlayer(),
    });

    expect(order).toEqual(["mic", "socket"]);
    expect(call.state).toBe(STREAM_STATE.LIVE);
  });

  it("tells the user why the mic failed instead of preparing it forever", async () => {
    // الطلب المعلّق: المتصفح بيسيب getUserMedia معلّقة لو نافذة الإذن ما اتجاوبتش.
    const hanging = { getUserMedia: () => new Promise(() => {}) };
    const source = createMicSource({ win: { navigator: { mediaDevices: hanging } }, timeoutMs: 10 });
    await expect(source.start(() => {})).rejects.toMatchObject({ code: "mic_timeout" });

    const denied = {
      getUserMedia: async () => {
        throw Object.assign(new Error("Permission denied"), { name: "NotAllowedError" });
      },
    };
    await expect(createMicSource({ win: { navigator: { mediaDevices: denied } } }).start(() => {})).rejects.toMatchObject({
      code: "mic_denied",
    });

    const missing = {
      getUserMedia: async () => {
        throw Object.assign(new Error("no device"), { name: "NotFoundError" });
      },
    };
    await expect(createMicSource({ win: { navigator: { mediaDevices: missing } } }).start(() => {})).rejects.toMatchObject({
      code: "mic_missing",
    });

    const none = { navigator: {} };
    await expect(createMicSource({ win: none }).start(() => {})).rejects.toMatchObject({ code: "mic_missing" });
  });

  it("stops a mic stream that arrives after the deadline", async () => {
    const track = { stop: vi.fn() };
    let release;
    const late = {
      getUserMedia: () =>
        new Promise((resolve) => {
          release = () => resolve({ getTracks: () => [track] });
        }),
    };
    const source = createMicSource({ win: { navigator: { mediaDevices: late } }, timeoutMs: 5 });
    await expect(source.start(() => {})).rejects.toMatchObject({ code: "mic_timeout" });
    release();
    await new Promise((r) => setTimeout(r, 5));
    expect(track.stop).toHaveBeenCalledTimes(1);
  });

  it("every mic failure has one instruction the user can act on", async () => {
    for (const code of ["mic_denied", "mic_timeout", "mic_missing", "mic_failed"]) {
      expect(MIC_ERROR_TEXT[code]).toBeTruthy();
      expect(MIC_ERROR_TEXT[code]).not.toMatch(/[a-z]{4,}/i); // مفيش إنجليزي وسط الرسالة
    }
  });

  it("reads the session_id the server actually returns", async () => {
    // الشكل الحقيقي من POST /voice/sessions: {"session_id": ..., "tenant_id": ..., "state": ...}
    const apiFn = vi.fn(async () => ({
      session_id: "8f14e45f-ceea-467a-9f0b-1c0d1e2f3a4b",
      tenant_id: "b7c1f0d2-1111-4222-8333-944455556666",
      persona: "merchant_assistant",
      state: "CONFIGURING",
      scopes: ["analytics:read"],
      trace_id: "voice-8f14e45f",
      last_completed_turn: 0,
    }));

    const id = await openVoiceSession({ apiFn, clientKey: "screen-key" });

    expect(id).toBe("8f14e45f-ceea-467a-9f0b-1c0d1e2f3a4b");
  });

  it("returns null when the server sends no id at all", async () => {
    const apiFn = vi.fn(async () => ({ state: "CONFIGURING" }));

    expect(await openVoiceSession({ apiFn, clientKey: "screen-key" })).toBeNull();
  });

  it("does not call a call live before the socket is actually open", async () => {
    // سوكت بيفضل معلّق: مفيش open ومفيش close. الشاشة مكانتش بتعرف الفرق.
    const pending = { ...fakeSocket(), readyState: 0 };
    const notes = [];
    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => pending,
      micFactory: () => fakeMic(),
      playerFactory: () => fakePlayer(),
      onSocket: (event) => notes.push(event.type),
      openTimeoutMs: 10,
    });

    expect(call.state).toBe(STREAM_STATE.FAILED);
    expect(notes).toEqual(["unopened"]);
  });

  it("reports open and goes live when the handshake completes", async () => {
    const socket = fakeSocket();
    socket.readyState = 0;
    const notes = [];
    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => {
        setTimeout(() => {
          socket.readyState = 1;
          socket.onopen?.();
        }, 0);
        return socket;
      },
      micFactory: () => fakeMic(),
      playerFactory: () => fakePlayer(),
      onSocket: (event) => notes.push(event.type),
      openTimeoutMs: 50,
    });

    expect(call.state).toBe(STREAM_STATE.LIVE);
    expect(notes).toContain("open");
  });
});

describe("the model's audio actually comes back", () => {
  it("counts every audio delta the socket delivers and reports it as it arrives", async () => {
    const socket = fakeSocket();
    const player = fakePlayer();
    const heard = [];

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => fakeMic(),
      playerFactory: () => player,
      onAudio: (counts) => heard.push(counts),
    });

    // The socket opened and the mic started, but nothing has been heard yet.
    expect(call.audio).toEqual({ frames: 0, bytes: 0 });

    socket.onmessage({ data: new ArrayBuffer(480) });
    socket.onmessage({ data: new ArrayBuffer(480) });

    expect(player.play).toHaveBeenCalledTimes(2);
    expect(call.audio).toEqual({ frames: 2, bytes: 960 });
    expect(heard).toEqual([
      { frames: 1, bytes: 480 },
      { frames: 2, bytes: 960 },
    ]);
  });

  it("does not count a control frame as audio", async () => {
    const socket = fakeSocket();
    const player = fakePlayer();

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => fakeMic(),
      playerFactory: () => player,
    });

    socket.onmessage({ data: JSON.stringify({ type: "session.started" }) });

    expect(player.play).not.toHaveBeenCalled();
    expect(call.audio).toEqual({ frames: 0, bytes: 0 });
  });
});

describe("a suspended microphone is announced, not hidden", () => {
  it("says the browser needs a gesture, and resumeMic clears it once audio flows", async () => {
    const socket = fakeSocket();
    let suspended = true;
    const mic = {
      ...fakeMic(),
      isSuspended: () => suspended,
      resume: vi.fn(async () => {
        suspended = false;
      }),
    };
    const prompts = [];

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => mic,
      playerFactory: () => fakePlayer(),
      onNeedsGesture: (info) => prompts.push(info),
    });

    // The call is live, but the screen was told the mic is silent.
    expect(call.state).toBe(STREAM_STATE.LIVE);
    expect(prompts).toEqual([{ reason: "suspended" }]);

    expect(await call.resumeMic()).toBe(true);
    expect(mic.resume).toHaveBeenCalledTimes(1);
  });

  it("says nothing when the microphone is already running", async () => {
    const prompts = [];
    await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => fakeSocket(),
      micFactory: () => ({ ...fakeMic(), isSuspended: () => false }),
      playerFactory: () => fakePlayer(),
      onNeedsGesture: (info) => prompts.push(info),
    });

    expect(prompts).toEqual([]);
  });
});
