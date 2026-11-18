import { describe, expect, it } from "vitest";
import { changedValues, parseNumber, parseReasons, policyDefinitions, policyErrorMessage, reasonsToText, startingValues } from "./shopPolicy";

const def = (o) => ({ domain: "pos", enforced: true, scopes: ["tenant", "branch"], default: 30, min_value: 0, max_value: 365, ...o });

describe("policyDefinitions", () => {
  it("keeps only enforced, tenant-wide settings of the domain", () => {
    const defs = [
      def({ key: "a" }),
      def({ key: "not-wired", enforced: false }),
      def({ key: "other-domain", domain: "print" }),
      def({ key: "branch-only", scopes: ["branch"] }),
    ];
    expect(policyDefinitions(defs).map((d) => d.key)).toEqual(["a"]);
  });
  it("copes with nothing loaded yet", () => {
    expect(policyDefinitions(undefined)).toEqual([]);
  });
});

describe("startingValues and changedValues", () => {
  const defs = [def({ key: "a", default: 30 }), def({ key: "b", default: true })];
  it("starts from the server's effective value, else the default", () => {
    expect(startingValues(defs, { a: { value: 14 } })).toEqual({ a: 14, b: true });
  });
  it("lists only what changed", () => {
    const o = { a: 14, b: true };
    expect(changedValues(defs, o, { a: 14, b: true })).toEqual([]);
    expect(changedValues(defs, o, { a: 21, b: true })).toEqual([{ key: "a", value: 21 }]);
  });
  it("compares lists by content", () => {
    const d = [def({ key: "r", default: [] })];
    expect(changedValues(d, { r: ["x"] }, { r: ["x"] })).toEqual([]);
    expect(changedValues(d, { r: ["x"] }, { r: ["x", "y"] })).toHaveLength(1);
  });
});

describe("parseNumber", () => {
  const d = def({ key: "a" });
  it("accepts a number inside the bounds, including 0", () => {
    expect(parseNumber(d, "14")).toEqual({ value: 14 });
    expect(parseNumber(d, "0")).toEqual({ value: 0 });
  });
  it("refuses out-of-range and non-numbers", () => {
    expect(parseNumber(d, "400").error).toMatch(/365/);
    expect(parseNumber(d, "-1").error).toMatch(/0/);
    expect(parseNumber(d, "abc").error).toBeTruthy();
  });
  it("treats an empty box as 'no limit' only when the setting has no default", () => {
    expect(parseNumber(def({ key: "x", default: null }), "")).toEqual({ value: null });
    expect(parseNumber(d, "").error).toBeTruthy();
  });
});

describe("reasons text", () => {
  it("one per line, trimmed, no blanks or repeats", () => {
    expect(parseReasons(" size \n\ndefect\nsize\n  \nwrong_item")).toEqual(["size", "defect", "wrong_item"]);
  });
  it("round-trips", () => {
    expect(parseReasons(reasonsToText(["a", "b"]))).toEqual(["a", "b"]);
    expect(parseReasons(undefined)).toEqual([]);
  });
});

describe("policyErrorMessage", () => {
  it("explains a permission refusal and passes anything else through", () => {
    expect(policyErrorMessage(new Error("missing permission: settings:write"))).toMatch(/صلاحية/);
    expect(policyErrorMessage(new Error("value out of range"))).toBe("value out of range");
    expect(policyErrorMessage(null)).toBe("تعذّر الحفظ");
  });
});
