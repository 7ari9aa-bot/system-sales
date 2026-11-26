import { describe, expect, test } from "vitest";
import { drSummary, rowPairs } from "./DataPanels";

describe("rowPairs", () => {
  test("humanises the fields worth reading and skips the plumbing", () => {
    expect(
      rowPairs({ id: "abc", source_type: "csv", status: "done", row_count: 12, created_by_id: "u" }),
    ).toEqual([
      ["Source Type", "csv"],
      ["Status", "done"],
      ["Row Count", "12"],
    ]);
  });

  test("booleans and empty values read the way a person writes them", () => {
    expect(rowPairs({ verified: true, revoked: false, note: null })).toEqual([
      ["Verified", "✓"],
      ["Revoked", "✗"],
      ["Note", "—"],
    ]);
  });

  test("nested collections are dropped instead of printed as JSON", () => {
    expect(rowPairs({ status: "ok", payload: { a: 1 } })).toEqual([["Status", "ok"]]);
  });

  test("a non-object row never throws", () => {
    expect(rowPairs(null)).toEqual([]);
  });
});

describe("drSummary", () => {
  const position = {
    rpo_minutes: 5,
    rto_minutes: 30,
    backup_retention_days: 30,
    pitr_window_days: 7,
    restore_test_cron: "0 2 * * 0",
    last_restore_test_at: "2026-11-20T02:00:00+00:00",
    last_restore_test_status: "passed",
    restore_test_overdue: false,
    healthy: true,
  };

  test("states recoverability as a claim, not as a configured number", () => {
    const pairs = Object.fromEntries(drSummary(position));
    expect(pairs.Recoverable).toBe("yes");
    expect(pairs["Drill overdue"]).toBe("no");
  });

  test("an overdue drill is not allowed to read as healthy", () => {
    const pairs = Object.fromEntries(
      drSummary({ ...position, healthy: false, restore_test_overdue: true, last_restore_test_status: null }),
    );
    expect(pairs.Recoverable).toBe("not proven");
    expect(pairs["Drill overdue"]).toBe("yes");
    expect(pairs["Last drill result"]).toBe("—");
  });

  test("a missing position renders nothing rather than zeros", () => {
    expect(drSummary(null)).toEqual([]);
  });
});
