import { describe, expect, test } from "vitest";
import { rowPairs } from "./DataPanels";

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
