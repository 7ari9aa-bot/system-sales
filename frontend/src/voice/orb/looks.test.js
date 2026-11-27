/** الكرة: القواعد اللي بتخلّي شكلها يقول الحقيقة.
 *
 *  المشهد نفسه WebGL ومش بيتست هنا، لكن اللي بيتست هو اللي بيهم: إن الكرة بتنوّر وتتوهّج
 *  لما الصوت يوصل، وإنها بتميّز مين بيتكلم، وإن اللي مش متاح ما بيكسرش الشاشة.
 */
import { describe, expect, it } from "vitest";

import { approach, cameraRig, clamp01, orbLook, orbMode } from "./looks";
import { createLevelMeter, float32Level, pcm16Level } from "./levels";

function pcm16(samples) {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  samples.forEach((value, index) => view.setInt16(index * 2, value, true));
  return buffer;
}

describe("orbMode", () => {
  it("says who is talking, not just that the call is live", () => {
    expect(orbMode({ state: "live", mic: 0.4, assistant: 0 })).toBe("listening");
    expect(orbMode({ state: "live", mic: 0, assistant: 0.5 })).toBe("speaking");
    expect(orbMode({ state: "live", mic: 0, assistant: 0 })).toBe("thinking");
  });

  it("keeps the assistant ahead of the mic when both are talking", () => {
    expect(orbMode({ state: "live", mic: 0.3, assistant: 0.6 })).toBe("speaking");
  });

  it("maps every failure state to the red look", () => {
    for (const state of ["failed", "refused", "unavailable", "not_found", "closed"]) {
      expect(orbMode({ state })).toBe("failed");
    }
  });

  it("treats opening and connecting as one state", () => {
    expect(orbMode({ state: "opening" })).toBe("opening");
    expect(orbMode({ state: "requesting" })).toBe("opening");
    expect(orbMode({ state: "connecting" })).toBe("opening");
  });
});

describe("orbLook", () => {
  it("lights the orb up when the assistant speaks", () => {
    const quiet = orbLook({ state: "live", assistant: 0 });
    const loud = orbLook({ state: "live", assistant: 0.9 });
    expect(loud.emissive).toBeGreaterThan(quiet.emissive);
    expect(loud.glow).toBeGreaterThan(quiet.glow);
    expect(loud.scale).toBeGreaterThan(quiet.scale);
    expect(loud.distortion).toBeGreaterThan(quiet.distortion);
  });

  it("changes colour between states so the screen is readable with no sound", () => {
    const listening = orbLook({ state: "live", mic: 0.5 });
    const thinking = orbLook({ state: "live" });
    const failed = orbLook({ state: "failed" });
    expect(listening.hue).not.toBe(thinking.hue);
    expect(failed.hue).toBeLessThan(30);
  });

  it("freezes motion when the user asked for reduced motion", () => {
    const look = orbLook({ state: "live", assistant: 1, reduced: true });
    expect(look.spin).toBe(0);
    expect(look.distortion).toBeLessThan(0.05);
  });

  it("never returns a value outside 0..1 for anything the shader clamps", () => {
    const look = orbLook({ state: "live", mic: 9, assistant: -4 });
    for (const key of ["emissive", "distortion", "glow"]) {
      expect(look[key]).toBeGreaterThanOrEqual(0);
      expect(look[key]).toBeLessThanOrEqual(1);
    }
  });
});

describe("level measurement", () => {
  it("reads silence as zero and full scale as one", () => {
    expect(pcm16Level(pcm16([0, 0, 0, 0]))).toBe(0);
    expect(pcm16Level(pcm16([32767, -32768, 32767, -32768]))).toBe(1);
  });

  it("rises with the voice instead of snapping between on and off", () => {
    const quiet = pcm16Level(pcm16([200, -200, 200, -200]));
    const loud = pcm16Level(pcm16([9000, -9000, 9000, -9000]));
    expect(quiet).toBeGreaterThan(0);
    expect(loud).toBeGreaterThan(quiet);
  });

  it("survives an empty or broken packet without throwing", () => {
    expect(pcm16Level(null)).toBe(0);
    expect(pcm16Level(new ArrayBuffer(0))).toBe(0);
    expect(float32Level([])).toBe(0);
    expect(float32Level([0.5, -0.5, 0.5, -0.5])).toBeGreaterThan(0);
  });

  it("drops back to zero when the sound stops", () => {
    const meter = createLevelMeter();
    meter.setAssistant(0.8, 1000);
    expect(meter.read(1050).assistant).toBeCloseTo(0.8);
    expect(meter.read(5000).assistant).toBe(0);
  });

  it("keeps the mic and the assistant apart", () => {
    const meter = createLevelMeter();
    meter.setMic(0.6, 1000);
    meter.setAssistant(0.1, 1000);
    const levels = meter.read(1010);
    expect(levels.mic).toBeCloseTo(0.6);
    expect(levels.assistant).toBeCloseTo(0.1);
  });
});

describe("approach", () => {
  it("moves part of the way and never overshoots", () => {
    expect(approach(0, 1, 0.25)).toBeCloseTo(0.25);
    expect(approach(0.9, 1, 1)).toBe(1);
    expect(approach(0, 1, 0)).toBe(0);
    expect(clamp01(3)).toBe(1);
    expect(clamp01(Number.NaN)).toBe(0);
  });
});

describe("cameraRig", () => {
  it("moves the camera with the pointer, so the whole page has depth", () => {
    const center = cameraRig({ pointerX: 0, pointerY: 0, energy: 0, time: 0 });
    const right = cameraRig({ pointerX: 1, pointerY: 0, energy: 0, time: 0 });
    const up = cameraRig({ pointerX: 0, pointerY: 1, energy: 0, time: 0 });
    expect(right.x).toBeGreaterThan(center.x);
    expect(up.y).toBeGreaterThan(center.y);
  });

  it("pushes in when the voice gets loud, and never inside the orb", () => {
    const quiet = cameraRig({ energy: 0 });
    const loud = cameraRig({ energy: 1 });
    expect(loud.z).toBeLessThan(quiet.z);
    expect(loud.z).toBeGreaterThan(2);
  });

  it("keeps a slow drift so the page is alive even in silence", () => {
    const a = cameraRig({ time: 0 });
    const b = cameraRig({ time: 6 });
    expect(a.x).not.toBe(b.x);
    expect(Math.abs(a.x)).toBeLessThan(0.2);
  });

  it("clamps wild pointers instead of flying out of the scene", () => {
    const wild = cameraRig({ pointerX: 40, pointerY: -40, energy: 5 });
    expect(wild.x).toBeLessThanOrEqual(0.5);
    expect(wild.y).toBeGreaterThanOrEqual(-0.4);
    const broken = cameraRig({ pointerX: Number.NaN, pointerY: undefined, energy: Number.NaN });
    for (const key of ["x", "y", "z", "lookY"]) expect(Number.isFinite(broken[key])).toBe(true);
  });
});
