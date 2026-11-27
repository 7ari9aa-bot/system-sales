/** جلسة الصوت: التوكن، الغرفة، المايك، والقفل — من غير شبكة ولا WebRTC حقيقي. */
import { describe, expect, it, vi } from "vitest";

import { VOICE_STATE, describeState, requestTransport, startVoiceSession } from "./session";

const CREDENTIAL = {
  provider: "livekit",
  url: "wss://voice-agent-test.livekit.cloud",
  token: "token-abc",
  room: "session-1",
  identity: "session-session-1",
  expires_at: "2026-11-27T09:10:00Z",
};

function fakeRoom(overrides = {}) {
  return {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn().mockResolvedValue(undefined),
    localParticipant: { setMicrophoneEnabled: vi.fn().mockResolvedValue(undefined) },
    ...overrides,
  };
}

function apiReturning(payload) {
  return vi.fn().mockResolvedValue(payload);
}

function apiFailing(status) {
  return vi.fn().mockRejectedValue(Object.assign(new Error("failed"), { status }));
}

describe("requestTransport", () => {
  it("بيطلب توكن الجلسة من الـcontrol plane", async () => {
    const apiFn = apiReturning(CREDENTIAL);
    const result = await requestTransport("session-1", { apiFn });
    expect(result.ok).toBe(true);
    expect(result.credential.token).toBe("token-abc");
    expect(apiFn).toHaveBeenCalledWith("/voice/sessions/session-1/transport", { method: "POST" });
  });

  it.each([
    [409, VOICE_STATE.REFUSED],
    [404, VOICE_STATE.NOT_FOUND],
    [503, VOICE_STATE.UNAVAILABLE],
    [500, VOICE_STATE.FAILED],
  ])("بيرجّع الحالة الصح لـ%s", async (status, expected) => {
    const result = await requestTransport("session-1", { apiFn: apiFailing(status) });
    expect(result.ok).toBe(false);
    expect(result.state).toBe(expected);
    expect(result.message).toBe(describeState(expected));
  });

  it("توكن ناقص مايتعاملش كنجاح", async () => {
    const result = await requestTransport("session-1", { apiFn: apiReturning({ url: "wss://x" }) });
    expect(result.ok).toBe(false);
    expect(result.state).toBe(VOICE_STATE.FAILED);
  });
});

describe("startVoiceSession", () => {
  it("بيدخل الغرفة بالتوكن ويفتح المايك ويقفل بالـstop", async () => {
    const room = fakeRoom();
    const states = [];
    const session = await startVoiceSession({
      sessionId: "session-1",
      roomFactory: async () => room,
      apiFn: apiReturning(CREDENTIAL),
      onState: (state) => states.push(state),
    });

    expect(session.ok).toBe(true);
    expect(room.connect).toHaveBeenCalledWith(CREDENTIAL.url, CREDENTIAL.token);
    expect(room.localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    expect(states).toEqual([VOICE_STATE.REQUESTING, VOICE_STATE.CONNECTING, VOICE_STATE.LIVE]);

    await session.stop();
    expect(room.disconnect).toHaveBeenCalledTimes(1);
    expect(states.at(-1)).toBe(VOICE_STATE.CLOSED);
  });

  it("لو السيرفر رفض، مابيفتحش غرفة أصلاً", async () => {
    const roomFactory = vi.fn();
    const session = await startVoiceSession({
      sessionId: "session-1",
      roomFactory,
      apiFn: apiFailing(409),
    });
    expect(session.ok).toBe(false);
    expect(session.state).toBe(VOICE_STATE.REFUSED);
    expect(roomFactory).not.toHaveBeenCalled();
  });

  it("لو المايك اتقفل من المتصفح، بيقفل الغرفة وبيقول للمستخدم", async () => {
    const room = fakeRoom({
      localParticipant: {
        setMicrophoneEnabled: vi.fn().mockRejectedValue(new Error("NotAllowedError")),
      },
    });
    const session = await startVoiceSession({
      sessionId: "session-1",
      roomFactory: async () => room,
      apiFn: apiReturning(CREDENTIAL),
    });
    expect(session.ok).toBe(false);
    expect(session.state).toBe(VOICE_STATE.FAILED);
    expect(room.disconnect).toHaveBeenCalledTimes(1);
  });

  it("لو الاتصال بالغرفة فشل، بيقفل اللي اتفتح", async () => {
    const room = fakeRoom({ connect: vi.fn().mockRejectedValue(new Error("ice failed")) });
    const session = await startVoiceSession({
      sessionId: "session-1",
      roomFactory: async () => room,
      apiFn: apiReturning(CREDENTIAL),
    });
    expect(session.ok).toBe(false);
    expect(room.disconnect).toHaveBeenCalledTimes(1);
  });
});
