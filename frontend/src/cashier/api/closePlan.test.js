import { describe, expect, it } from "vitest";
import { closeBody, closeProblems, countsDrawer, gapMinor, gapText } from "./closePlan";

const ON = { take_payments: true };
const OFF = { take_payments: false };

describe("a till with no drawer", () => {
  it("counts nothing and sends nothing", () => {
    expect(countsDrawer(OFF)).toBe(false);
    expect(countsDrawer(undefined)).toBe(false);
    expect(closeProblems({ rules: OFF, counted: "", expected: "100" })).toEqual([]);
    expect(closeBody({ rules: OFF, counted: "50", expected: "100", reason: "x" })).toBeUndefined();
  });
});

describe("the gap", () => {
  it("is counted minus expected in cents", () => {
    expect(gapMinor("80", "100")).toBe(-2000);
    expect(gapMinor("100.50", "100")).toBe(50);
    expect(gapMinor("100", "100.00")).toBe(0);
  });
  it("has no cent drift on awkward decimals", () => {
    expect(gapMinor("0.30", "0.10")).toBe(20);
    expect(gapMinor("1.005", "1")).toBe(1);
  });
  it("is unknown for a blank, negative or non-numeric count or an unknown expected", () => {
    for (const c of ["", null, "-5", "abc"]) expect(gapMinor(c, "100")).toBeNull();
    expect(gapMinor("50", null)).toBeNull();
  });
  it("is shown signed as text", () => {
    expect(gapText("80", "100")).toBe("-20.00");
    expect(gapText("105", "100")).toBe("5.00");
    expect(gapText("", "100")).toBeNull();
  });
});

describe("what the cashier still owes before closing", () => {
  const base = { rules: ON, expected: "100" };
  it("needs the count first", () => {
    expect(closeProblems({ ...base, counted: "" })).toEqual(["count"]);
    expect(closeProblems({ ...base, counted: "abc" })).toEqual(["count"]);
  });
  it("needs nothing when the drawer matches", () => {
    expect(closeProblems({ ...base, counted: "100" })).toEqual([]);
  });
  it("needs a reason for a gap when the owner requires one, over or short", () => {
    expect(closeProblems({ ...base, counted: "90" })).toEqual(["reason"]);
    expect(closeProblems({ ...base, counted: "110" })).toEqual(["reason"]);
    expect(closeProblems({ ...base, counted: "90", reason: "  " })).toEqual(["reason"]);
    expect(closeProblems({ ...base, counted: "90", reason: "سلفة" })).toEqual([]);
  });
  it("does not need a reason when the owner turned that off", () => {
    expect(closeProblems({ ...base, counted: "90", reasonRequired: false })).toEqual([]);
  });
  it("needs a manager only above the limit, and never when the limit is 0", () => {
    const g = { ...base, reason: "x" };
    expect(closeProblems({ ...g, counted: "90", threshold: 5 })).toEqual(["approval"]);
    expect(closeProblems({ ...g, counted: "95", threshold: 5 })).toEqual([]); // exactly at the limit
    expect(closeProblems({ ...g, counted: "90", threshold: 0 })).toEqual([]);
    expect(closeProblems({ ...g, counted: "90", threshold: 5, canApprove: true })).toEqual([]);
  });
  it("is not ready while the expected cash is unknown, even with a count typed", () => {
    // The dialog's button also waits on `expected`; this keeps the two guards from drifting apart.
    expect(closeProblems({ rules: ON, counted: "100", expected: null })).toEqual(["count"]);
    expect(closeProblems({ rules: ON, counted: "100", expected: undefined })).toEqual(["count"]);
  });
  it("reports the reason and the approval together", () => {
    expect(closeProblems({ ...base, counted: "90", threshold: 5 })).toEqual(["reason", "approval"]);
  });
  it("refuses a reason over 500 characters", () => {
    expect(closeProblems({ ...base, counted: "90", reason: "ا".repeat(501) })).toEqual(["reason_too_long"]);
  });
});

describe("the request body", () => {
  it("sends the count as a wire amount", () => {
    expect(closeBody({ rules: ON, counted: "100", expected: "100" })).toEqual({ counted_cash: "100.00" });
  });
  it("adds the reason only when there is a gap and a reason", () => {
    expect(closeBody({ rules: ON, counted: "90", expected: "100", reason: " سلفة " })).toEqual({ counted_cash: "90.00", variance_reason: "سلفة" });
    expect(closeBody({ rules: ON, counted: "100", expected: "100", reason: "x" })).toEqual({ counted_cash: "100.00" });
    expect(closeBody({ rules: ON, counted: "90", expected: "100", reason: "" })).toEqual({ counted_cash: "90.00" });
  });
  it("throws on a count the server would refuse rather than sending it", () => {
    expect(() => closeBody({ rules: ON, counted: "-1", expected: "100" })).toThrow();
    expect(() => closeBody({ rules: ON, counted: "abc", expected: "100" })).toThrow();
  });
});
