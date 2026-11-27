import { describe, expect, it, vi } from "vitest";
import {
  STREAM_STATE,
  openVoiceSession,
  describeStreamState,
  floatToPcm16,
  resampleTo,
  startBrowserCall,
  streamStateForClose,
  streamStateForStatus,
  websocketUrl,
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
    expect(describeStreamState(STREAM_STATE.REFUSED)).toContain("صوت");
  });

  it("talks to the same origin as the API, over ws", () => {
    expect(websocketUrl("/api/v1/voice/sessions/x/stream", () => "https://api.example.com/api/v1/voice/sessions/x/stream"))
      .toBe("wss://api.example.com/api/v1/voice/sessions/x/stream");
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

  it("closes the socket when the mic is refused", async () => {
    const socket = fakeSocket();
    const mic = {
      start: vi.fn(async () => {
        throw new Error("no microphone");
      }),
      stop: vi.fn(),
    };
    const player = fakePlayer();

    const call = await startBrowserCall({
      sessionId: SESSION,
      apiFn: ticketOk,
      wsFactory: async () => socket,
      micFactory: () => mic,
      playerFactory: () => player,
    });

    expect(call.state).toBe(STREAM_STATE.FAILED);
    expect(socket.closed).toEqual([1000]);
    expect(player.stop).toHaveBeenCalledTimes(1);
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
});
