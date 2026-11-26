/**
 * A screen can hold both a plain setting and one that needs approval.
 *
 * The bulk endpoint refuses an APPROVAL_REQUIRED key outright, so sending one batch made
 * the whole save fail and took the direct edits down with it. These tests pin the split,
 * and pin that every status the backend emits has its own label instead of "pending".
 */
import { describe, expect, it } from "vitest";
import { splitSaveChanges } from "@/components/settings/useSettings";
import { STATUS_META } from "@/components/settings/ChangeRequestList";

describe("splitSaveChanges", () => {
  it("puts an approval-required key in its own batch", () => {
    const { direct, needsApproval } = splitSaveChanges(
      { "print.copies": 2, "pos.max_discount_pct": 15 },
      ["pos.max_discount_pct"],
    );
    expect(direct).toEqual({ "print.copies": 2 });
    expect(needsApproval).toEqual({ "pos.max_discount_pct": 15 });
  });

  it("leaves everything direct when nothing needs approval", () => {
    const { direct, needsApproval } = splitSaveChanges({ "print.copies": 2 }, []);
    expect(direct).toEqual({ "print.copies": 2 });
    expect(needsApproval).toEqual({});
  });

  it("sends nothing direct when everything needs approval", () => {
    const { direct, needsApproval } = splitSaveChanges({ a: 1, b: 2 }, ["a", "b"]);
    expect(direct).toEqual({});
    expect(needsApproval).toEqual({ a: 1, b: 2 });
  });

  it("never loses or duplicates a key", () => {
    const changes = { a: 1, b: false, c: "x" };
    const { direct, needsApproval } = splitSaveChanges(changes, ["b"]);
    expect(Object.keys(direct).sort()).toEqual(["a", "c"]);
    expect(Object.keys(needsApproval)).toEqual(["b"]);
    expect({ ...direct, ...needsApproval }).toEqual(changes);
  });

  it("keeps a false value instead of dropping it as empty", () => {
    const { direct } = splitSaveChanges({ "print.show_logo": false }, []);
    expect(direct).toEqual({ "print.show_logo": false });
  });
});

describe("change request statuses", () => {
  const backendStates = [
    "pending_approval",
    "approved",
    "rejected",
    "applying",
    "applied",
    "failed",
    "stale",
    "cancelled",
    "expired",
  ];

  it("has a label for every state the backend emits", () => {
    for (const state of backendStates) {
      expect(STATUS_META[state], state).toBeTruthy();
      expect(STATUS_META[state].labelAr).toBeTruthy();
      expect(STATUS_META[state].labelEn).toBeTruthy();
    }
  });

  it("does not describe a finished request as pending", () => {
    for (const state of ["applied", "failed", "stale", "cancelled", "expired"]) {
      expect(STATUS_META[state].labelEn.toLowerCase()).not.toContain("pending");
      expect(STATUS_META[state].tone).not.toBe("warning");
    }
  });
});
