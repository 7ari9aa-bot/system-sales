import { describe, expect, it } from "vitest";
import { foldCode, foldText, foldedIncludes, toAsciiDigits } from "./searchText";

// (what the catalogue holds, what a cashier types instead) - the same pairs the backend test uses.
const SPELLINGS = [
  ["فستان أحمر إيطالي", "احمر"],
  ["فستان أحمر إيطالي", "ايطالي"],
  ["حقيبة يد جلد", "حقيبه"],
  ["جاكت شتوي", "شتوى"],
  ["مِعطف صوف", "معطف"],
  ["فستان سهرة", "فُستان"],
  ["Premium Shirt", "premium"],
];

describe("foldedIncludes", () => {
  it.each(SPELLINGS)("%s is found by typing %s", (stored, typed) => {
    expect(foldedIncludes(stored, typed)).toBe(true);
  });
  it("a different word does not match", () => {
    expect(foldedIncludes("فستان أحمر", "اخضر")).toBe(false);
    expect(foldedIncludes("حقيبة", "حذاء")).toBe(false);
  });
  it("prose keeps its spaces: two words do not match one fused word", () => {
    expect(foldedIncludes("فستاناحمر", "فستان احمر")).toBe(false);
  });
  it("an empty term matches nothing", () => {
    expect(foldedIncludes("anything", "   ")).toBe(false);
  });
});

describe("codes", () => {
  it("Arabic-Indic and Persian digits become ASCII", () => {
    expect(toAsciiDigits("R-٠٠٢٩٩٩")).toBe("R-002999");
    expect(toAsciiDigits("۱۲۳٤٥٦")).toBe("123456");
  });
  it("a barcode typed on an Arabic keyboard finds the stored barcode", () => {
    expect(foldedIncludes("6221234567890", "٦٢٢١٢٣٤٥٦٧٨٩٠")).toBe(true);
    expect(foldedIncludes("6221234567890", "٤٥٦٧٨٩٠")).toBe(true); // a fragment
  });
  it("a receipt number is found with or without its dashes", () => {
    expect(foldedIncludes("POS-20261022-030560", "POS-20261022-030560")).toBe(true);
    expect(foldedIncludes("POS-20261022-030560", "POS20261022030560")).toBe(true);
    expect(foldedIncludes("POS-20261022-030560", "pos 20261022 030560")).toBe(true);
    expect(foldedIncludes("POS-20261022-030560", "POS-٢٠٢٦١٠٢٢")).toBe(true);
    expect(foldedIncludes("POS-20261022-030560", "POS-99999999")).toBe(false);
  });
  it("foldCode drops separators", () => {
    expect(foldCode("R-002 999/1")).toBe("r0029991");
  });
  it("foldText folds every spelling of a letter to one", () => {
    expect(foldText("أإآٱ")).toBe("اااا");
    expect(foldText("ة")).toBe("ه");
    expect(foldText("ىئ")).toBe("يي");
  });
});
