import { describe, expect, it } from "vitest";
import {
  SIDEBAR_DEFAULT,
  SIDEBAR_MAX,
  SIDEBAR_MIN,
  SIDEBAR_STEP,
  STORAGE_KEY,
  clampWidth,
  readSaved,
  widthFromDrag,
  widthFromKey,
  writeSaved,
} from "./sidebarSize";

const memory = (initial = {}) => {
  const data = { ...initial };
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, data };
};

describe("clampWidth", () => {
  it("keeps a width inside the limits", () => {
    expect(clampWidth(300)).toBe(300);
    expect(clampWidth(SIDEBAR_MIN)).toBe(SIDEBAR_MIN);
    expect(clampWidth(SIDEBAR_MAX)).toBe(SIDEBAR_MAX);
  });
  it("pulls an out-of-range width back to the nearest limit", () => {
    expect(clampWidth(10)).toBe(SIDEBAR_MIN);
    expect(clampWidth(5000)).toBe(SIDEBAR_MAX);
    expect(clampWidth(-40)).toBe(SIDEBAR_MIN);
  });
  it("rounds to a whole pixel", () => {
    expect(clampWidth(300.6)).toBe(301);
  });
  it("falls back to the default for anything that is not a number", () => {
    for (const bad of [undefined, null, NaN, "abc", "", "  ", {}, Infinity, -Infinity]) {
      expect(clampWidth(bad)).toBe(SIDEBAR_DEFAULT);
    }
  });
  it("accepts a number saved as text", () => {
    expect(clampWidth("350")).toBe(350);
  });
});

describe("widthFromDrag", () => {
  const base = { startWidth: 280, startX: 500 };
  it("in Arabic, pulling the handle to the left makes the list wider", () => {
    expect(widthFromDrag({ ...base, currentX: 450, dir: "rtl" })).toBe(330);
  });
  it("in Arabic, pushing it to the right makes the list narrower", () => {
    expect(widthFromDrag({ ...base, currentX: 540, dir: "rtl" })).toBe(240);
  });
  it("in English it is the other way round", () => {
    expect(widthFromDrag({ ...base, currentX: 550, dir: "ltr" })).toBe(330);
    expect(widthFromDrag({ ...base, currentX: 460, dir: "ltr" })).toBe(240);
  });
  it("never goes past either limit however far the pointer travels", () => {
    expect(widthFromDrag({ ...base, currentX: -4000, dir: "rtl" })).toBe(SIDEBAR_MAX);
    expect(widthFromDrag({ ...base, currentX: 9000, dir: "rtl" })).toBe(SIDEBAR_MIN);
  });
  it("is measured from where the drag started, not from the last move", () => {
    expect(widthFromDrag({ startWidth: 300, startX: 100, currentX: 100, dir: "ltr" })).toBe(300);
  });
});

describe("widthFromKey", () => {
  it("the arrow pointing away from the list widens it, by one step", () => {
    expect(widthFromKey({ width: 280, key: "ArrowLeft", dir: "rtl" })).toBe(280 + SIDEBAR_STEP);
    expect(widthFromKey({ width: 280, key: "ArrowRight", dir: "ltr" })).toBe(280 + SIDEBAR_STEP);
  });
  it("the other arrow narrows it", () => {
    expect(widthFromKey({ width: 280, key: "ArrowRight", dir: "rtl" })).toBe(280 - SIDEBAR_STEP);
    expect(widthFromKey({ width: 280, key: "ArrowLeft", dir: "ltr" })).toBe(280 - SIDEBAR_STEP);
  });
  it("Home and End jump to the limits", () => {
    expect(widthFromKey({ width: 300, key: "Home", dir: "rtl" })).toBe(SIDEBAR_MIN);
    expect(widthFromKey({ width: 300, key: "End", dir: "rtl" })).toBe(SIDEBAR_MAX);
  });
  it("stops at the limits", () => {
    expect(widthFromKey({ width: SIDEBAR_MAX, key: "ArrowLeft", dir: "rtl" })).toBe(SIDEBAR_MAX);
    expect(widthFromKey({ width: SIDEBAR_MIN, key: "ArrowRight", dir: "rtl" })).toBe(SIDEBAR_MIN);
  });
  it("returns null for a key the handle does not use, so the page can ignore it", () => {
    expect(widthFromKey({ width: 280, key: "a", dir: "rtl" })).toBeNull();
    expect(widthFromKey({ width: 280, key: "ArrowUp", dir: "rtl" })).toBeNull();
  });
});

describe("saved choice", () => {
  it("starts at the default, open, when nothing was saved", () => {
    expect(readSaved(memory())).toEqual({ width: SIDEBAR_DEFAULT, collapsed: false });
  });
  it("gives back what was written", () => {
    const s = memory();
    writeSaved(s, { width: 340, collapsed: true });
    expect(readSaved(s)).toEqual({ width: 340, collapsed: true });
  });
  it("clamps what it writes, so the stored value is always usable", () => {
    const s = memory();
    writeSaved(s, { width: 99999, collapsed: false });
    expect(JSON.parse(s.data[STORAGE_KEY]).width).toBe(SIDEBAR_MAX);
  });
  it("survives damaged or foreign saved data", () => {
    for (const raw of ["not json", "null", "[]", '"x"', '{"width":"wide","collapsed":"yes"}']) {
      const out = readSaved(memory({ [STORAGE_KEY]: raw }));
      expect(out.width).toBeGreaterThanOrEqual(SIDEBAR_MIN);
      expect(out.width).toBeLessThanOrEqual(SIDEBAR_MAX);
      expect(out.collapsed).toBe(false);
    }
  });
  it("treats only a real true as collapsed", () => {
    expect(readSaved(memory({ [STORAGE_KEY]: '{"width":300,"collapsed":"true"}' })).collapsed).toBe(false);
    expect(readSaved(memory({ [STORAGE_KEY]: '{"width":300,"collapsed":true}' })).collapsed).toBe(true);
  });
  it("never throws when storage is missing or refuses to write", () => {
    expect(() => readSaved(undefined)).not.toThrow();
    expect(() => writeSaved(undefined, { width: 300, collapsed: false })).not.toThrow();
    const full = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("quota"); } };
    expect(readSaved(full)).toEqual({ width: SIDEBAR_DEFAULT, collapsed: false });
    expect(() => writeSaved(full, { width: 300, collapsed: true })).not.toThrow();
  });
});
