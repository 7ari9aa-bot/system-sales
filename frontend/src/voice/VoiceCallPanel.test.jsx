/** زر المكالمة: النص من الحالة، والشكل الابتدائي قبل أي اتصال. */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import VoiceCallPanel, { buttonLabel } from "./VoiceCallPanel";
import { VOICE_STATE } from "./session";

describe("buttonLabel", () => {
  it("بيبدأ المكالمة من الوقوف", () => {
    expect(buttonLabel(VOICE_STATE.IDLE)).toBe("ابدأ المكالمة");
  });

  it("بيوري إنه بيفتح وهو مشغول", () => {
    expect(buttonLabel(VOICE_STATE.REQUESTING)).toBe("بيفتح...");
    expect(buttonLabel(VOICE_STATE.CONNECTING)).toBe("بيفتح...");
  });

  it("بيبقى زر إقفال وهو شغال", () => {
    expect(buttonLabel(VOICE_STATE.LIVE)).toBe("اقفل المكالمة");
  });
});

describe("VoiceCallPanel", () => {
  it("بيترندر من غير مكالمة وهو ساكت", () => {
    const html = renderToStaticMarkup(<VoiceCallPanel sessionId="session-1" />);
    expect(html).toContain('data-testid="voice-call-panel"');
    expect(html).toContain('data-state="idle"');
    expect(html).toContain("ابدأ المكالمة");
    expect(html).not.toContain("اقفل المكالمة");
  });
});
