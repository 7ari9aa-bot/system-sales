import { describe, expect, it } from "vitest";
import {
  cleanNote,
  habitEvidence,
  isFull,
  memoryErrorMessage,
  noteDraftState,
  sourceLabel,
  visibleNotes,
  visibleSuggestions,
} from "./ownerMemory";

describe("cleanNote", () => {
  it("trims, and refuses empty or whitespace-only text", () => {
    expect(cleanNote("  بحب الشاي  ", 500)).toBe("بحب الشاي");
    expect(cleanNote("", 500)).toBeNull();
    expect(cleanNote("   \n ", 500)).toBeNull();
    expect(cleanNote(null, 500)).toBeNull();
    expect(cleanNote(undefined, 500)).toBeNull();
    expect(cleanNote(42, 500)).toBeNull();
  });
  it("refuses text over the limit and accepts exactly the limit", () => {
    expect(cleanNote("a".repeat(500), 500)).toBe("a".repeat(500));
    expect(cleanNote("a".repeat(501), 500)).toBeNull();
  });
  it("measures the trimmed text, not the padded one", () => {
    expect(cleanNote(`  ${"a".repeat(500)}  `, 500)).toBe("a".repeat(500));
  });
  it("does not enforce a limit it was not given", () => {
    expect(cleanNote("a".repeat(5000), undefined)).toBe("a".repeat(5000));
  });
});

describe("noteDraftState", () => {
  it("counts down the room left and allows sending", () => {
    expect(noteDraftState("abc", 10)).toEqual({
      length: 3,
      remaining: 7,
      over: false,
      canSend: true,
    });
  });
  it("blocks an empty draft", () => {
    expect(noteDraftState("   ", 10).canSend).toBe(false);
    expect(noteDraftState("", 10).canSend).toBe(false);
  });
  it("blocks a draft over the limit and reports how far over", () => {
    const s = noteDraftState("a".repeat(12), 10);
    expect(s.over).toBe(true);
    expect(s.canSend).toBe(false);
    expect(s.remaining).toBe(-2);
  });
  it("allows a draft of exactly the limit", () => {
    expect(noteDraftState("a".repeat(10), 10).canSend).toBe(true);
  });
});

describe("isFull", () => {
  it("is full at the cap and over, not below it", () => {
    expect(isFull(49, 50)).toBe(false);
    expect(isFull(50, 50)).toBe(true);
    expect(isFull(51, 50)).toBe(true);
  });
  it("is never full when the cap is unknown", () => {
    expect(isFull(1000, undefined)).toBe(false);
  });
});

describe("memoryErrorMessage", () => {
  it("shows the server's own Arabic reason for a refusal", () => {
    const err = Object.assign(new Error("الملاحظة دي شكلها سر"), {
      status: 422,
    });
    expect(memoryErrorMessage(err)).toBe("الملاحظة دي شكلها سر");
  });
  it("shows the reason for a conflict such as a full memory", () => {
    const err = Object.assign(new Error("الذاكرة ممتلئة"), { status: 409 });
    expect(memoryErrorMessage(err)).toBe("الذاكرة ممتلئة");
  });
  it("hides a server failure behind a generic line instead of its internals", () => {
    const err = Object.assign(
      new Error("InvalidRequestError: closed transaction"),
      { status: 500 },
    );
    expect(memoryErrorMessage(err)).toBe("حصلت مشكلة. جرّب تاني بعد شوية.");
  });
  it("falls back when there is no message or no status (a dropped connection)", () => {
    expect(memoryErrorMessage(new Error(""))).toBe(
      "حصلت مشكلة. جرّب تاني بعد شوية.",
    );
    expect(memoryErrorMessage(null)).toBe("حصلت مشكلة. جرّب تاني بعد شوية.");
    expect(memoryErrorMessage(new Error("Failed to fetch"))).toBe(
      "حصلت مشكلة. جرّب تاني بعد شوية.",
    );
  });
  it("answers in English when asked to", () => {
    expect(memoryErrorMessage(null, false)).toBe(
      "Something went wrong. Try again in a moment.",
    );
  });
});

describe("sourceLabel", () => {
  it("tells a note the owner asked for from one the assistant inferred", () => {
    expect(sourceLabel("explicit")).not.toBe(sourceLabel("inferred"));
    expect(sourceLabel("inferred")).toContain("استنتجتها");
    expect(sourceLabel("explicit")).toContain("قلتلي");
  });
  it("treats an unknown source as the owner's own", () => {
    expect(sourceLabel("whatever")).toBe(sourceLabel("explicit"));
  });
});

describe("visibleNotes", () => {
  it("keeps the server's order and returns a copy", () => {
    const input = [{ id: "b" }, { id: "a" }];
    const out = visibleNotes(input);
    expect(out.map((n) => n.id)).toEqual(["b", "a"]);
    expect(out).not.toBe(input);
  });
  it("returns an empty list for anything that is not a list", () => {
    expect(visibleNotes(undefined)).toEqual([]);
    expect(visibleNotes(null)).toEqual([]);
    expect(visibleNotes({})).toEqual([]);
  });
});

describe("habit suggestions", () => {
  const ok = {
    period: "last_7_days",
    text: "بتفضّل تشوف الأرقام عن آخر 7 أيام",
    count: 8,
  };

  it("keeps a well-formed suggestion", () => {
    expect(visibleSuggestions([ok])).toEqual([ok]);
  });

  it("is empty for anything that is not a list", () => {
    expect(visibleSuggestions(undefined)).toEqual([]);
    expect(visibleSuggestions(null)).toEqual([]);
    expect(visibleSuggestions("x")).toEqual([]);
  });

  it("drops a suggestion with no period or no text rather than showing a blank row", () => {
    expect(
      visibleSuggestions([
        { text: "x" },
        { period: "today" },
        { period: "today", text: "  " },
      ]),
    ).toEqual([]);
  });

  it("drops a period that is not one of the five the server can accept", () => {
    expect(
      visibleSuggestions([{ period: "../x", text: "x", count: 5 }]),
    ).toEqual([]);
  });

  it("never mutates its input", () => {
    const input = [ok];
    visibleSuggestions(input);
    expect(input).toEqual([ok]);
  });

  it("says how many times the owner asked, in Arabic and English", () => {
    expect(habitEvidence(8, true)).toContain("8");
    expect(habitEvidence(8, false)).toContain("8");
    expect(habitEvidence(8, true)).not.toEqual(habitEvidence(8, false));
  });

  it("shows no evidence line for a missing or nonsensical count", () => {
    expect(habitEvidence(undefined, true)).toBe("");
    expect(habitEvidence(0, true)).toBe("");
    expect(habitEvidence(-3, false)).toBe("");
    expect(habitEvidence("8", true)).toBe("");
  });
});
