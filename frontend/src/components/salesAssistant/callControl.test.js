import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import { STREAM_STATE } from "../../voice/browserCall";
import { I18nProvider } from "@/lib/i18n";
import { createCallController } from "./callControl";

function harness({ sessionId = "sess-1", state = STREAM_STATE.LIVE, message = "" } = {}) {
  const stop = vi.fn();
  const openSession = vi.fn(async () => sessionId);
  const startCall = vi.fn(async ({ onState }) => {
    onState(state, message);
    return { stop, state };
  });
  const changes = [];
  const ended = vi.fn();
  const controller = createCallController({
    openSession,
    startCall,
    onChange: (payload) => changes.push(payload),
    onEnd: ended,
  });
  return { controller, openSession, startCall, stop, changes, ended };
}

describe("callControl", () => {
  it("opens one session, starts one call, and stops it on the second press", async () => {
    const h = harness();

    await h.controller.toggle();
    expect(h.openSession).toHaveBeenCalledTimes(1);
    expect(h.startCall.mock.calls[0][0].sessionId).toBe("sess-1");
    expect(h.controller.calling).toBe(true);

    await h.controller.toggle();
    expect(h.stop).toHaveBeenCalledTimes(1);
    expect(h.controller.calling).toBe(false);
    expect(h.ended).toHaveBeenCalledTimes(1);
  });

  it("surfaces a refusal and never reports the call as live", async () => {
    const h = harness({ state: STREAM_STATE.REFUSED, message: "هذه الجلسة لا تدعم الصوت المباشر حالياً." });

    await h.controller.toggle();

    expect(h.controller.calling).toBe(false);
    expect(h.changes.at(-1)).toEqual({
      calling: false,
      error: "هذه الجلسة لا تدعم الصوت المباشر حالياً.",
      state: STREAM_STATE.REFUSED,
    });
    expect(h.stop).toHaveBeenCalledTimes(1);
  });

  it("does not show an error when the call ends normally", async () => {
    const h = harness({ state: STREAM_STATE.CLOSED, message: "المكالمة اتقفلت." });

    await h.controller.toggle();

    expect(h.changes.at(-1)).toEqual({ calling: false, error: null, state: STREAM_STATE.CLOSED });
  });

  it("reports a failure to start instead of staying stuck on calling", async () => {
    const openSession = vi.fn(async () => {
      throw new Error("offline");
    });
    const changes = [];
    const controller = createCallController({
      openSession,
      startCall: vi.fn(),
      onChange: (payload) => changes.push(payload),
    });

    await controller.toggle();

    expect(controller.calling).toBe(false);
    expect(changes.at(-1).error).toBeTruthy();
  });
});

describe("the composer shows the call button", () => {
  it("renders a real call control beside dictation", async () => {
    const Composer = (await import("./Composer")).default;
    const html = renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(Composer, { value: "", onChange() {}, onSend() {}, disabled: false, error: null }),
      ),
    );

    expect(html).toContain('data-testid="assistant-call"');
  });

  it("interrupt silences the call without ending it", async () => {
    const handle = { stop: vi.fn(), interrupt: vi.fn(), state: STREAM_STATE.LIVE };
    const controller = createCallController({
      openSession: async () => "s-1",
      startCall: async () => handle,
    });

    await controller.toggle();
    expect(controller.interrupt()).toBe(true);

    expect(handle.interrupt).toHaveBeenCalledTimes(1);
    // المقاطعة مش إنهاء: المكالمة لسه شغالة والزر لسه في وضع "شغّال".
    expect(handle.stop).not.toHaveBeenCalled();
    expect(controller.calling).toBe(true);
  });

  it("interrupt before a call does nothing and says so", () => {
    const controller = createCallController({
      openSession: async () => "s-1",
      startCall: async () => ({ stop: vi.fn(), state: STREAM_STATE.LIVE }),
    });

    expect(controller.interrupt()).toBe(false);
  });


  it("stale session is dropped once and a fresh call opens instead of showing 404", async () => {
    const openSession = vi.fn(async () => `s-${openSession.mock.calls.length}`);
    const startCall = vi
      .fn()
      .mockImplementationOnce(async () => ({ state: STREAM_STATE.NOT_FOUND, stop: vi.fn() }))
      .mockImplementationOnce(async ({ onState }) => {
        onState(STREAM_STATE.LIVE);
        return { state: STREAM_STATE.LIVE, stop: vi.fn(), interrupt: vi.fn() };
      });
    const resetSession = vi.fn(async () => {});
    const controller = createCallController({ openSession, startCall, resetSession });

    await controller.toggle();

    expect(resetSession).toHaveBeenCalledTimes(1);
    expect(openSession).toHaveBeenCalledTimes(2);
    expect(startCall).toHaveBeenCalledTimes(2);
    expect(startCall.mock.calls[1][0].sessionId).toBe("s-2");
    expect(controller.calling).toBe(true);
  });

  it("does not retry forever when the fresh session is refused too", async () => {
    const openSession = vi.fn(async () => "s-1");
    const startCall = vi.fn(async () => ({ state: STREAM_STATE.NOT_FOUND, stop: vi.fn() }));
    const resetSession = vi.fn(async () => {});
    const controller = createCallController({ openSession, startCall, resetSession });

    await controller.toggle();

    expect(openSession).toHaveBeenCalledTimes(2);
    expect(controller.calling).toBe(false);
  });
});

describe("callControl and the real audio", () => {
  it("passes the microphone gesture and the audio count through to the screen", async () => {
    const stop = vi.fn();
    const resumeMic = vi.fn(async () => true);
    const openSession = vi.fn(async () => "sess-1");
    const startCall = vi.fn(async ({ onState }) => {
      onState(STREAM_STATE.LIVE, "");
      return { stop, resumeMic, state: STREAM_STATE.LIVE, audio: { frames: 3, bytes: 1440 } };
    });
    const controller = createCallController({ openSession, startCall });

    // Before any call there is nothing to resume and nothing heard.
    expect(await controller.resumeMic()).toBe(false);
    expect(controller.audio).toEqual({ frames: 0, bytes: 0 });

    await controller.toggle();

    expect(controller.audio).toEqual({ frames: 3, bytes: 1440 });
    expect(await controller.resumeMic()).toBe(true);
    expect(resumeMic).toHaveBeenCalledTimes(1);
  });
});
