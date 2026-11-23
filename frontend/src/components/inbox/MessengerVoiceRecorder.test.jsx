import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import MessengerVoiceRecorder, { MESSENGER_RECORDING_TYPES, pickMessengerRecordingType } from "./MessengerVoiceRecorder";

describe("pickMessengerRecordingType", () => {
  test("offers only mp4, because Messenger does not play ogg or webm", () => {
    expect(pickMessengerRecordingType((t) => t === "audio/ogg;codecs=opus")).toBeNull();
    expect(pickMessengerRecordingType((t) => t === "audio/ogg")).toBeNull();
    expect(pickMessengerRecordingType((t) => t === "audio/webm;codecs=opus")).toBeNull();
    expect(pickMessengerRecordingType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickMessengerRecordingType(() => true)).toBe("audio/mp4;codecs=mp4a.40.2");
    expect(pickMessengerRecordingType()).toBeNull();
  });
  test("every offered type is one the Send API accepts", () => {
    for (const t of MESSENGER_RECORDING_TYPES) expect(t.startsWith("audio/mp4")).toBe(true);
  });
});

describe("MessengerVoiceRecorder", () => {
  test("renders the recording bar with cancel and send controls, in both languages", () => {
    const ar = renderToStaticMarkup(React.createElement(MessengerVoiceRecorder, { lang: "ar" }));
    expect(ar).toContain('data-testid="messenger-voice-recorder"');
    expect(ar).toContain('data-testid="messenger-voice-cancel"');
    expect(ar).toContain('data-testid="messenger-voice-stop"');
    expect(ar).toContain("إلغاء التسجيل");
    const en = renderToStaticMarkup(React.createElement(MessengerVoiceRecorder, { lang: "en" }));
    expect(en).toContain("Cancel recording");
    expect(en).toContain("0:00");
  });
  test("the send button stays disabled until the microphone is actually recording", () => {
    const out = renderToStaticMarkup(React.createElement(MessengerVoiceRecorder, { lang: "en" }));
    expect(out).toMatch(/data-testid="messenger-voice-stop"[^>]*disabled|disabled[^>]*data-testid="messenger-voice-stop"/);
  });
});
