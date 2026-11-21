import { describe, expect, it } from "vitest";
import { closeBody, closeProblems, gapText, readCountedCash } from "./closePlan";

const rules = { take_payments: true };

// The cashier types the count on whatever keyboard the shop has. A count that cannot be read must
// stop the close with "count the drawer"; it must never become a different amount.
describe("the counted cash is read the way it was typed", () => {
  it.each([
    ["500", "500"],
    ["500.5", "500.5"],
    [" 500 ", "500"],
    ["٥٠٠", "500"],
    ["٥٠٠٫٥", "500.5"],
    ["٥٠٠.٥", "500.5"],
    ["۳۵۰۰", "3500"],
    ["500,5", "500.5"],
    ["0,5", "0.5"],
    ["0", "0"],
    ["٠", "0"],
    ["1,000", "1000"],
    ["1,000.50", "1000.50"],
    ["1 000", "1000"],
    ["٣٬٥٠٠", "3500"],
    ["١٢،٣٤٥", "12345"],
    ["12,345,678", "12345678"],
    ["1\u00a0000", "1000"],
    // two digits after a comma is cents, not a thousands group
    ["1,00", "1.00"],
    ["12,50", "12.50"],
    ["999,999", "999999"],
    // three digits after a comma is a thousands group, never three decimals
    ["500,555", "500555"],
  ])("%s is %s", (typed, read) => {
    expect(readCountedCash(typed)).toBe(read);
  });

  it.each(["", "abc", "-5", "5e2", "1,00,0", "1.000,5", "1,0000", "1,5,5", ",5", "5,", "1,000,", ".5", "5.", "٫٥", "1..5", null, undefined,
    // the first group of a thousands number is one to three digits
    "1234,567",
    "12345,678",
    // a thousands number never starts with zero: 0,555 is not 555
    "0,555",
    "00,500",
  ])(
    "%s is refused, never guessed",
    (typed) => {
      expect(readCountedCash(typed)).toBeNull();
    },
  );

  it("a count in Arabic digits closes with the same amount as in Latin digits", () => {
    const latin = closeBody({ rules, counted: "1250.50", expected: "1250.50", reason: "" });
    const arabic = closeBody({ rules, counted: "١٢٥٠٫٥٠", expected: "1250.50", reason: "" });
    expect(arabic).toEqual(latin);
    expect(arabic).toEqual({ counted_cash: "1250.50" });
  });

  it("a thousands separator is not a decimal point: 1,000 is a thousand, not one", () => {
    expect(closeBody({ rules, counted: "1,000", expected: "1000.00", reason: "" })).toEqual({ counted_cash: "1000.00" });
    expect(gapText("1,000", "1000.00")).toBe("0.00");
  });

  it("an empty drawer counted as zero is a real count with a real gap", () => {
    expect(gapText("٠", "500.00")).toBe("-500.00");
    expect(closeProblems({ rules, counted: "٠", expected: "500.00", reason: "" })).toContain("reason");
    expect(closeBody({ rules, counted: "٠", expected: "500.00", reason: "فتح بلا نقد" })).toEqual({
      counted_cash: "0.00",
      variance_reason: "فتح بلا نقد",
    });
  });

  it("an unreadable count blocks the close and sends no made-up amount", () => {
    for (const bad of ["1,00,0", "abc", "", "-5"]) {
      expect(closeProblems({ rules, counted: bad, expected: "500.00", reason: "x" }), bad).toEqual(["count"]);
      expect(gapText(bad, "500.00"), bad).toBeNull();
    }
  });

  it("a till with no drawer still sends nothing", () => {
    expect(closeBody({ rules: { take_payments: false }, counted: "٥٠٠", expected: "500.00", reason: "" })).toBeUndefined();
    expect(closeProblems({ rules: { take_payments: false }, counted: "", expected: "500.00", reason: "" })).toEqual([]);
  });

  it("plain Latin input behaves exactly as before", () => {
    expect(closeBody({ rules, counted: "500", expected: "500.00", reason: "" })).toEqual({ counted_cash: "500.00" });
    expect(closeBody({ rules, counted: "480.5", expected: "500.00", reason: "عجز" })).toEqual({
      counted_cash: "480.50",
      variance_reason: "عجز",
    });
    expect(gapText("480.5", "500.00")).toBe("-19.50");
  });
});
