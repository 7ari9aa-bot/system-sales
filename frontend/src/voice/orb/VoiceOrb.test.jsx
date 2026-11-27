/** الكرة على الشاشة: لازم تظهر في كل الأحوال، وتقول الحالة اللي هي عليها.
 *
 *  الاختبارات هنا node (زي باقي شاشة المكالمة) — بتتأكد من الـmarkup مش من الـcanvas.
 *  غياب WebGL في البيئة دي مش عيب نستره: ده نفس مسار متصفح قديم أو جهاز مقفول الرسومات،
 *  ولازم يطلع بديل شغال بدل شاشة فاضية.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import VoiceOrb, { prefersReducedMotion, supportsWebgl } from "./VoiceOrb";

const html = (element) => renderToStaticMarkup(element);

describe("supportsWebgl", () => {
  it("says no when the canvas cannot give a context", () => {
    expect(supportsWebgl({ createElement: () => ({ getContext: () => null }) })).toBe(false);
  });

  it("says yes when a context comes back", () => {
    expect(supportsWebgl({ createElement: () => ({ getContext: () => ({}) }) })).toBe(true);
  });

  it("does not throw when the browser explodes or there is no document", () => {
    const doc = {
      createElement: () => ({
        getContext: () => {
          throw new Error("no gpu");
        },
      }),
    };
    expect(supportsWebgl(doc)).toBe(false);
    expect(supportsWebgl(undefined)).toBe(false);
  });
});

describe("prefersReducedMotion", () => {
  it("follows the system setting", () => {
    expect(prefersReducedMotion({ matchMedia: () => ({ matches: true }) })).toBe(true);
    expect(prefersReducedMotion({ matchMedia: () => ({ matches: false }) })).toBe(false);
  });

  it("defaults to motion when matchMedia is missing or throws", () => {
    expect(prefersReducedMotion({})).toBe(false);
    expect(
      prefersReducedMotion({
        matchMedia: () => {
          throw new Error("nope");
        },
      })
    ).toBe(false);
  });
});

describe("VoiceOrb", () => {
  it("renders a still orb instead of nothing when there is no WebGL", () => {
    const markup = html(<VoiceOrb state="live" forceFallback />);
    expect(markup).toContain('data-testid="voice-orb"');
    expect(markup).toContain('data-testid="voice-orb-fallback"');
    expect(markup).toContain('data-mode="thinking"');
  });

  it("carries the state so the screen never lies about what is happening", () => {
    expect(html(<VoiceOrb state="live" mic={0} assistant={0.6} forceFallback />)).toContain('data-mode="thinking"');
    expect(html(<VoiceOrb state="failed" forceFallback />)).toContain('data-mode="failed"');
    expect(html(<VoiceOrb state="opening" forceFallback />)).toContain('data-mode="opening"');
  });

  it("paints the fallback with the hue of its mode", () => {
    const opening = html(<VoiceOrb state="opening" forceFallback />);
    const failed = html(<VoiceOrb state="failed" forceFallback />);
    expect(opening).toMatch(/hsl\(172 72% 55%\)/);
    expect(failed).toMatch(/hsl\(4 72% 55%\)/);
  });

  it("renders without a meter, because the call may not have started yet", () => {
    expect(html(<VoiceOrb state="idle" forceFallback />)).toContain('data-mode="idle"');
  });
});
