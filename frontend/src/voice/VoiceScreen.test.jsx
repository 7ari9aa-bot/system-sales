/** شاشة المكالمة: النص من الحالة، والدايرة والمؤقّت موجودين، والقاطع مسموح بس وقت الكلام. */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import VoiceScreen, { formatElapsed, screenView } from "./VoiceScreen";

describe("screenView", () => {
  it("بيوري إنه بيفتح قبل ما الصوت يبدأ", () => {
    expect(screenView({ state: "opening" })).toEqual({
      text: "بجهّز المايك…",
      failed: false,
      canInterrupt: false,
    });
  });

  it("وقت الكلام النص بيقول كده والقاطع مسموح", () => {
    const view = screenView({ state: "live" });
    expect(view.text).toBe("بتتكلم دلوقتي");
    expect(view.canInterrupt).toBe(true);
    expect(view.failed).toBe(false);
  });

  it("رسالة السيرفر بتغلب النص الافتراضي وحالة الفشل بتتعرف", () => {
    const view = screenView({ state: "not_found", message: "الجلسة مش موجودة أو مش بتاعتك." });
    expect(view.text).toBe("الجلسة مش موجودة أو مش بتاعتك.");
    expect(view.failed).toBe(true);
    expect(view.canInterrupt).toBe(false);
  });

  it("كل حالات الفشل بتتحسب فشل", () => {
    for (const state of ["refused", "unavailable", "not_found", "failed", "closed"]) {
      expect(screenView({ state }).failed).toBe(true);
    }
  });

  it("اللغة بتتغيّر من غير ما الكود يتغيّر", () => {
    expect(screenView({ state: "live", labels: { live: "You are speaking" } }).text).toBe("You are speaking");
  });
});

describe("VoiceScreen", () => {
  it("مش بيرسم حاجة والمكالمة مقفولة", () => {
    expect(renderToStaticMarkup(<VoiceScreen open={false} />)).toBe("");
  });

  it("بيرسم الدايرة والمؤقّت وزر الإقفال", () => {
    const html = renderToStaticMarkup(<VoiceScreen open state="live" />);
    expect(html).toContain('data-testid="voice-screen"');
    expect(html).toContain('data-testid="voice-screen-state"');
    expect(html).toContain("00:00");
    expect(html).toContain('data-testid="voice-screen-close"');
    expect(html).toContain('data-testid="voice-screen-interrupt"');
  });

  it("القاطع مقفول قبل ما الصوت يبدأ", () => {
    const html = renderToStaticMarkup(<VoiceScreen open state="opening" />);
    expect(html).toContain('disabled=""');
  });

  it("المؤقّت بيتنسّق دقايق وثواني", () => {
    expect(formatElapsed(0)).toBe("00:00");
    expect(formatElapsed(75)).toBe("01:15");
  });
});
