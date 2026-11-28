import { describe, expect, it } from "vitest";
import { BUILT_IN_OPTIONS, colourHex, swatchHex, normaliseOptions, resolveSizePreset, sizePresetChoices } from "./shopOptions";
import { COLORS, SIZE_SETS } from "./uiConstants";

describe("normaliseOptions", () => {
  it("uses the shop's own lists when it has them", () => {
    const o = normaliseOptions({ customised: true, size_sets: { men: ["46", "48"] }, colours: [{ name: "زيتي", hex: "#112233" }] });
    expect(o.sizeSets).toEqual({ men: ["46", "48"] });
    expect(o.colours).toEqual([{ name: "زيتي", hex: "#112233" }]);
    expect(o.customised).toBe(true);
  });
  it("keeps the built-in lists for a missing, empty or malformed answer", () => {
    for (const raw of [undefined, null, {}, { size_sets: [], colours: "x" }, { size_sets: { a: [] }, colours: [{ name: " " }] }]) {
      const o = normaliseOptions(raw);
      expect(o.sizeSets).toEqual(SIZE_SETS);
      expect(o.colours.map((c) => c.name)).toEqual(COLORS.map((c) => c.name));
    }
  });
  it("drops a set with no sizes and a colour with no name but keeps the rest", () => {
    const o = normaliseOptions({ size_sets: { a: [], b: ["1"] }, colours: [{ name: "" }, { name: "أحمر", hex: null }] });
    expect(o.sizeSets).toEqual({ b: ["1"] });
    expect(o.colours).toEqual([{ name: "أحمر", hex: null }]);
  });
  it("turns sizes into text so a numeric size still matches what the matrix builds", () => {
    expect(normaliseOptions({ size_sets: { shoes: [40, 41] } }).sizeSets.shoes).toEqual(["40", "41"]);
  });
  it("built-ins are the old constants", () => {
    expect(BUILT_IN_OPTIONS.sizeSets).toEqual(SIZE_SETS);
    expect(BUILT_IN_OPTIONS.customised).toBe(false);
  });
});

describe("size choices", () => {
  it("labels built-in sets in Arabic and the shop's own sets by name", () => {
    expect(sizePresetChoices({ clothing: ["S"], men: ["46"] })).toEqual([
      { key: "clothing", label: "ملابس (S — XXL)" },
      { key: "men", label: "men" },
    ]);
  });
  it("falls back to the first set when the chosen one was removed", () => {
    expect(resolveSizePreset({ a: ["1"], b: ["2"] }, "b")).toBe("b");
    expect(resolveSizePreset({ a: ["1"], b: ["2"] }, "gone")).toBe("a");
    expect(resolveSizePreset({}, "x")).toBe("");
  });
});

describe("colourHex", () => {
  const cols = [{ name: "أسود", hex: "#000000" }, { name: "بلا", hex: null }];
  it("finds the swatch", () => expect(colourHex(cols, "أسود")).toBe("#000000"));
  it("gives a neutral swatch for an unknown colour or one with no hex", () => {
    expect(colourHex(cols, "قديم")).toBe("#A1A1AA");
    expect(colourHex(cols, "بلا")).toBe("#A1A1AA");
  });
});

describe("swatchHex", () => {
  const cols = [{ name: "أسود", hex: "#000000" }, { name: "بلا", hex: null }];
  it("prefers the shop's colour over what the caller passed", () => expect(swatchHex(cols, "أسود", "#FFFFFF")).toBe("#000000"));
  it("uses what the caller passed for a colour the shop does not list", () => expect(swatchHex(cols, "قديم", "#123456")).toBe("#123456"));
  it("is neutral grey when nothing is known", () => {
    expect(swatchHex(cols, "قديم", undefined)).toBe("#A1A1AA");
    expect(swatchHex(cols, "بلا", undefined)).toBe("#A1A1AA");
  });
});
