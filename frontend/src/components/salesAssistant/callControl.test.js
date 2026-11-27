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
    const h = harness({ state: STREAM_STATE.REFUSED, message: "الجلسة دي مش بتاخد صوت مباشر دلوقتي." });

    await h.controller.toggle();

    expect(h.controller.calling).toBe(false);
    expect(h.changes.at(-1)).toEqual({ calling: false, error: "الجلسة دي مش بتاخد صوت مباشر دلوقتي." });
    expect(h.stop).toHaveBeenCalledTimes(1);
  });

  it("does not show an error when the call ends normally", async () => {
    const h = harness({ state: STREAM_STATE.CLOSED, message: "المكالمة اتقفلت." });

    await h.controller.toggle();

    expect(h.changes.at(-1)).toEqual({ calling: false, error: null });
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
});
