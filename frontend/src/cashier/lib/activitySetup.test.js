import { describe, expect, it } from "vitest";
import {
  CHOOSABLE,
  COMING_SOON,
  canReopen,
  completeBody,
  isSelectable,
  normaliseSetup,
  presetCount,
  presetFor,
  sectorCards,
} from "./activitySetup";

const ASK = {
  state: "not_started",
  needs_setup: true,
  choices: ["general", "apparel"],
  presets: { apparel: "apparel_ground_shop" },
  preset_keys: { apparel: ["a", "b", "c"] },
};
const S = () => normaliseSetup(ASK);

describe("who is asked", () => {
  it("a new owner the server says to ask is asked", () => {
    expect(S().needsSetup).toBe(true);
  });
  it.each([
    ["nothing", undefined],
    ["null", null],
    ["a string", "yes"],
    ["a failed read shaped as an error", { error: { code: "x" } }],
    ["needs_setup missing", { ...ASK, needs_setup: undefined }],
    ["needs_setup false", { ...ASK, needs_setup: false }],
    ["needs_setup a truthy string", { ...ASK, needs_setup: "true" }],
    ["needs_setup 1", { ...ASK, needs_setup: 1 }],
    ["a skipped shop", { ...ASK, state: "skipped", needs_setup: false }],
    ["a finished shop", { ...ASK, state: "done", needs_setup: false }],
  ])("%s is never asked", (_n, raw) => {
    expect(normaliseSetup(raw).needsSetup).toBe(false);
  });
  it("a server that offers nothing we can show has nothing to ask", () => {
    expect(normaliseSetup({ ...ASK, choices: [] }).needsSetup).toBe(false);
    expect(normaliseSetup({ ...ASK, choices: ["pharmacy"] }).needsSetup).toBe(false);
    expect(normaliseSetup({ ...ASK, choices: "apparel" }).needsSetup).toBe(false);
  });
  it("a sector we cannot serve is dropped from what the server offered", () => {
    const s = normaliseSetup({ ...ASK, choices: ["apparel", "pharmacy", "restaurant"] });
    expect(s.choices).toEqual(["apparel"]);
  });
});

describe("reopening from settings", () => {
  it("is offered once the setup was answered or skipped, never while it is still due", () => {
    expect(canReopen({ state: "done" })).toBe(true);
    expect(canReopen({ state: "skipped" })).toBe(true);
    expect(canReopen({ state: "not_started" })).toBe(false);
    expect(canReopen(undefined)).toBe(false);
    expect(canReopen(null)).toBe(false);
    expect(canReopen("done")).toBe(false);
  });
});

describe("the cards", () => {
  it("clothing and general come first and can be picked", () => {
    const cards = sectorCards(S());
    expect(cards.slice(0, 2).map((c) => c.id)).toEqual(["general", "apparel"]);
    expect(cards.slice(0, 2).every((c) => c.disabled === false)).toBe(true);
  });
  it("every other sector is listed as coming soon and cannot be picked", () => {
    const soon = sectorCards(S()).filter((c) => c.disabled);
    expect(soon.map((c) => c.id)).toEqual(COMING_SOON.map((s) => s.key));
    expect(soon.length).toBe(5);
    expect(soon.every((c) => c.hint === "قريباً")).toBe(true);
    for (const c of soon) expect(isSelectable(S(), c.id)).toBe(false);
  });
  it("the choosable sectors are exactly the two the server serves", () => {
    expect([...CHOOSABLE].sort()).toEqual(["apparel", "general"]);
    expect(COMING_SOON.map((s) => s.key)).not.toContain("apparel");
    expect(COMING_SOON.map((s) => s.key)).not.toContain("general");
  });
  it("with only clothing offered, general is not a card to pick", () => {
    const s = normaliseSetup({ ...ASK, choices: ["apparel"] });
    expect(sectorCards(s).filter((c) => !c.disabled).map((c) => c.id)).toEqual(["apparel"]);
    expect(isSelectable(s, "general")).toBe(false);
  });
});

describe("what is sent", () => {
  it("clothing with the preset left on asks for the preset", () => {
    expect(completeBody(S(), "apparel", true)).toEqual({ vertical: "apparel", apply_preset: true });
  });
  it("clothing with the preset turned off sends no preset", () => {
    expect(completeBody(S(), "apparel", false)).toEqual({ vertical: "apparel", apply_preset: false });
  });
  it("only a real true counts as turned on", () => {
    for (const v of [undefined, null, 1, "true", "yes"]) {
      expect(completeBody(S(), "apparel", v).apply_preset).toBe(false);
    }
  });
  it("a general shop has no preset, so none is asked for even if the box was on", () => {
    expect(completeBody(S(), "general", true)).toEqual({ vertical: "general", apply_preset: false });
  });
  it.each(["pharmacy", "restaurant", "supermarket", "electronics", "wholesale", "", undefined, null, "x"])(
    "%s is never sent",
    (id) => {
      expect(completeBody(S(), id, true)).toBeNull();
    },
  );
  it("a sector the server did not offer is not sent even if it is one we know", () => {
    const s = normaliseSetup({ ...ASK, choices: ["apparel"] });
    expect(completeBody(s, "general", false)).toBeNull();
  });
});

describe("the preset summary", () => {
  it("names the preset and counts what it sets", () => {
    expect(presetFor(S(), "apparel")).toBe("apparel_ground_shop");
    expect(presetCount(S(), "apparel")).toBe(3);
  });
  it("a sector with no preset has none and zero", () => {
    expect(presetFor(S(), "general")).toBeNull();
    expect(presetCount(S(), "general")).toBe(0);
  });
  it("odd shapes read as none", () => {
    const s = normaliseSetup({ ...ASK, presets: { apparel: 5 }, preset_keys: { apparel: "abc" } });
    expect(presetFor(s, "apparel")).toBeNull();
    expect(presetCount(s, "apparel")).toBe(0);
  });
});
