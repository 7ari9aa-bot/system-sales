import { describe, expect, it } from "vitest";
import {
  generatingRow,
  sentQuestionIsAnswered,
  pollInterval,
  POLL_MS,
  questionAlreadyListed,
  stepsOf,
  withoutUnfinished,
} from "./progressSteps";

const done = { id: "a", role: "assistant", status: "completed", sequence_no: 2, content: "x" };
const open = (progress, seq = 4) => ({
  id: "b",
  role: "assistant",
  status: "generating",
  sequence_no: seq,
  content: "",
  progress,
});

describe("generatingRow", () => {
  it("is the unfinished assistant answer", () => {
    expect(generatingRow([done, open(["بقرا مبيعاتك"])]).id).toBe("b");
  });
  it("is null when every answer is finished", () => {
    expect(generatingRow([done])).toBeNull();
    expect(generatingRow([])).toBeNull();
    expect(generatingRow(undefined)).toBeNull();
  });
  it("ignores an unfinished USER row", () => {
    expect(generatingRow([{ role: "user", status: "generating", sequence_no: 3 }])).toBeNull();
  });
  it("takes the newest when the list holds two", () => {
    const older = { ...open(["a"], 2), id: "old" };
    const newer = { ...open(["b"], 6), id: "new" };
    expect(generatingRow([newer, older]).id).toBe("new");
    expect(generatingRow([older, newer]).id).toBe("new");
  });
});

describe("stepsOf", () => {
  it("keeps the server's order", () => {
    expect(stepsOf(open(["بقرا مبيعاتك", "بشوف المخزون"]))).toEqual([
      "بقرا مبيعاتك",
      "بشوف المخزون",
    ]);
  });
  it("is empty when the server wrote nothing", () => {
    expect(stepsOf(open(null))).toEqual([]);
    expect(stepsOf(open(undefined))).toEqual([]);
    expect(stepsOf(null)).toEqual([]);
  });
  it("drops blanks, non-strings and repeats instead of showing them", () => {
    expect(stepsOf(open(["  ", 3, null, "بقرا مبيعاتك", "بقرا مبيعاتك"]))).toEqual(["بقرا مبيعاتك"]);
  });
  it("ignores a progress that is not a list", () => {
    expect(stepsOf(open("بقرا مبيعاتك"))).toEqual([]);
    expect(stepsOf(open({ 0: "x" }))).toEqual([]);
  });
});

describe("withoutUnfinished", () => {
  it("removes the pending answer so it is not drawn twice", () => {
    expect(withoutUnfinished([done, open(["x"])]).map((m) => m.id)).toEqual(["a"]);
  });
  it("keeps finished and failed answers and every user row", () => {
    const failed = { id: "f", role: "assistant", status: "failed", sequence_no: 6 };
    const user = { id: "u", role: "user", status: "completed", sequence_no: 1 };
    expect(withoutUnfinished([user, done, failed]).map((m) => m.id)).toEqual(["u", "a", "f"]);
  });
  it("copes with nothing", () => {
    expect(withoutUnfinished(undefined)).toEqual([]);
  });
});

describe("pollInterval", () => {
  it("polls only while a question is in flight", () => {
    expect(pollInterval(true)).toBe(POLL_MS);
    expect(pollInterval(false)).toBe(false);
  });
  it("is slow enough not to hammer the server", () => {
    expect(POLL_MS).toBeGreaterThanOrEqual(1000);
  });
});

describe("questionAlreadyListed", () => {
  const asked = (content, seq = 3) => ({ id: "q", role: "user", status: "completed", sequence_no: seq, content });
  it("is true once the server returns the question the answer being written belongs to", () => {
    expect(questionAlreadyListed([asked("كام مبيعات الشهر؟"), open(["x"], 4)], "كام مبيعات الشهر؟")).toBe(true);
  });
  it("ignores surrounding whitespace", () => {
    expect(questionAlreadyListed([asked("  سؤال "), open(null, 4)], "سؤال")).toBe(true);
  });
  it("is false before the server has saved the question", () => {
    expect(questionAlreadyListed([done], "سؤال جديد")).toBe(false);
  });
  it("is false when the same words were asked EARLIER and this one is not in yet", () => {
    // an old turn with the same text, its answer finished: the new copy must still show
    const oldQ = asked("نفس السؤال", 1);
    const oldA = { ...done, sequence_no: 2 };
    expect(questionAlreadyListed([oldQ, oldA], "نفس السؤال")).toBe(false);
  });
  it("is false when nothing was typed", () => {
    expect(questionAlreadyListed([asked("x"), open(null, 4)], null)).toBe(false);
    expect(questionAlreadyListed([asked("x"), open(null, 4)], "")).toBe(false);
  });
  it("only matches the question right before the open answer, not any earlier one", () => {
    // an older row has the same words, but the open answer follows a different question
    const older = { id: "o", role: "user", status: "completed", sequence_no: 1, content: "سؤالي" };
    const mine = { id: "m", role: "user", status: "completed", sequence_no: 5, content: "سؤال تاني" };
    expect(questionAlreadyListed([older, mine, open(null, 6)], "سؤالي")).toBe(false);
  });
  it("is false when the open answer belongs to a different question", () => {
    expect(questionAlreadyListed([asked("سؤال تاني"), open(null, 4)], "سؤالي")).toBe(false);
  });
});

describe("sentQuestionIsAnswered", () => {
  const q = (seq, content = "x") => ({ id: `q${seq}`, role: "user", status: "completed", sequence_no: seq, content });
  const a = (seq, status) => ({ id: `a${seq}`, role: "assistant", status, sequence_no: seq, content: "y" });
  it("is true once the answer to the question just sent is finished", () => {
    expect(sentQuestionIsAnswered([q(1, "قديم"), a(2, "completed"), q(3, "جديد"), a(4, "completed")], "جديد")).toBe(true);
  });
  it("is true for a failed answer too, which has its own retry", () => {
    expect(sentQuestionIsAnswered([q(1, "جديد"), a(2, "failed")], "جديد")).toBe(true);
  });
  it("is FALSE right after sending, while the list still ends with an older answered question", () => {
    // the bug that hid the indicator for the first second of every question
    expect(sentQuestionIsAnswered([q(1, "قديم"), a(2, "completed")], "جديد")).toBe(false);
  });
  it("is false while the answer is still being written", () => {
    expect(sentQuestionIsAnswered([q(1, "قديم"), a(2, "completed"), q(3, "جديد"), a(4, "generating")], "جديد")).toBe(false);
  });
  it("is false when the question is saved but has no answer row yet", () => {
    expect(sentQuestionIsAnswered([q(1, "جديد")], "جديد")).toBe(false);
  });
  it("is not fooled by an OLD answered copy of the same words", () => {
    // asked the same thing earlier (answered); the new copy is saved and still open
    expect(
      sentQuestionIsAnswered([q(1, "نفسه"), a(2, "completed"), q(3, "نفسه"), a(4, "generating")], "نفسه"),
    ).toBe(false);
  });
  it("is false when nothing was sent or the list is empty", () => {
    expect(sentQuestionIsAnswered([q(1), a(2, "completed")], null)).toBe(false);
    expect(sentQuestionIsAnswered([], "x")).toBe(false);
    expect(sentQuestionIsAnswered(undefined, "x")).toBe(false);
  });
});
