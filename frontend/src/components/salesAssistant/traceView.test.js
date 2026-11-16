import { describe, expect, it } from "vitest";
import { canOpen, seconds, stepLabel, thinkingMs, traceSteps, traceSummary } from "./traceView";

const t = (k) =>
  ({
    "salesAssistant.trace.read": "قراءة",
    "salesAssistant.trace.rewrite": "إعادة كتابة الرد",
    "salesAssistant.trace.fill": "تكملة الرد",
    "salesAssistant.trace.round": "تفكير {n}",
  })[k] ?? k;

const model = (id, ms, extra = {}) => [
  { id, kind: "model", phase: "start", at_ms: 0, purpose: extra.purpose ?? "answer" },
  ...(ms == null ? [] : [{ id, kind: "model", phase: "end", at_ms: ms, ms, ok: true, reasoning: "think", tokens_out: 50, ...extra }]),
];
const tool = (id, ms, step = "بقرا المبيعات") => [
  { id, kind: "tool", phase: "start", at_ms: 0, tool: "si_metric", step },
  { id, kind: "tool", phase: "end", at_ms: ms, ms, ok: true },
];

describe("traceSteps", () => {
  it("joins start and end by id, in order, and keeps an open step open", () => {
    const s = traceSteps([...model(1, 4000), ...tool(2, 300), ...model(3, null)]);
    expect(s.map((x) => [x.id, x.kind, x.done])).toEqual([[1, "model", true], [2, "tool", true], [3, "model", false]]);
    expect(s[0].reasoning).toBe("think");
    expect(s[1].step).toBe("بقرا المبيعات");
    expect(s[2].ms).toBeUndefined();
  });
  it("ignores the summary, junk and unknown kinds", () => {
    const s = traceSteps([null, 5, { id: 0, kind: "summary", total_ms: 9 }, { id: 4, kind: "x", phase: "start" }, ...model(1, 10)]);
    expect(s.map((x) => x.id)).toEqual([1]);
    expect(traceSteps(undefined)).toEqual([]);
  });
  it("a failed round is marked and empty thinking is none", () => {
    const [r] = traceSteps(model(1, 10, { ok: false, reasoning: "  " }));
    expect(r.ok).toBe(false);
    expect(r.reasoning).toBeNull();
    expect(canOpen(r)).toBe(false);
  });
});

describe("timings", () => {
  it("thinking time is the summary's when there is one, else the finished rounds", () => {
    const running = [...model(1, 4000), ...tool(2, 300), ...model(3, null)];
    expect(thinkingMs(running)).toBe(4000);
    expect(thinkingMs([...running, { id: 0, kind: "summary", total_ms: 9000, model_ms: 7777 }])).toBe(7777);
    expect(traceSummary(running)).toBeNull();
  });
  it("seconds read with one decimal and never negative", () => {
    expect(seconds(6420)).toBe("6.4");
    expect(seconds(-1)).toBe("0.0");
    expect(seconds(undefined)).toBe("0.0");
  });
});

describe("labels", () => {
  it("numbers ordinary rounds only and names rewrites", () => {
    const steps = traceSteps([...model(1, 1), ...tool(2, 1), ...model(3, 1), ...model(4, 1, { purpose: "rewrite" }), ...model(5, 1, { purpose: "fill_gap" })]);
    expect(steps.map((s) => stepLabel(s, steps, t))).toEqual(["تفكير 1", "بقرا المبيعات", "تفكير 2", "إعادة كتابة الرد", "تكملة الرد"]);
  });
  it("a read with no wording falls back to a plain word", () => {
    const steps = traceSteps(tool(1, 5, null));
    expect(stepLabel(steps[0], steps, t)).toBe("قراءة");
  });
  it("only a finished round with thinking opens", () => {
    const steps = traceSteps([...model(1, 5), ...model(2, null), ...tool(3, 1)]);
    expect(steps.map(canOpen)).toEqual([true, false, false]);
  });
  it("a read never opens even if the server sent a reasoning field on it", () => {
    const [r] = traceSteps([
      { id: 1, kind: "tool", phase: "start", tool: "si_metric", step: "x" },
      { id: 1, kind: "tool", phase: "end", ms: 5, ok: true, reasoning: "should be ignored" },
    ]);
    expect(r.reasoning).toBeUndefined();
    expect(canOpen(r)).toBe(false);
  });
  it("a round that has not ended cannot open even if thinking arrived early", () => {
    const [r] = traceSteps([
      { id: 1, kind: "model", phase: "start", purpose: "answer" },
      { id: 1, kind: "model", phase: "end", ms: 5, reasoning: "x" },
    ]);
    expect(canOpen({ ...r, done: false })).toBe(false);
  });
});
