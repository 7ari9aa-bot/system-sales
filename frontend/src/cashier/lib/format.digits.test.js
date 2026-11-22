import { describe, expect, it } from "vitest";
import { fmtDate, fmtDateTime } from "./format";

// Every number on the till is written with Latin digits (prices, quantities, the header clock). Dates came out in
// Arabic-Indic digits (٢٢/١١/٢٠٢٦) beside them, so one row mixed two scripts. Dates must match the rest.
// The locale adds invisible right-to-left marks around the slashes, so strip them before matching the shape.
const plain = (t) => t.replace(/[\u200e\u200f]/g, "");
const ARABIC_INDIC = /[\u0660-\u0669\u06F0-\u06F9]/;

describe("dates use Latin digits like every other figure", () => {
  const iso = "2026-11-22T04:50:19.000Z";
  it("fmtDate", () => {
    expect(fmtDate(iso)).not.toMatch(ARABIC_INDIC);
    expect(plain(fmtDate(iso))).toMatch(/^\d{2}\/\d{2}\/2026$/);
  });
  it("fmtDateTime", () => {
    expect(fmtDateTime(iso)).not.toMatch(ARABIC_INDIC);
    expect(plain(fmtDateTime(iso))).toMatch(/^\d{2}\/\d{2}\/2026 - \d{2}:\d{2}$/);
  });
  it("an empty date is still a dash", () => {
    expect(fmtDate(null)).toBe("—");
    expect(fmtDateTime("")).toBe("—");
  });
});
