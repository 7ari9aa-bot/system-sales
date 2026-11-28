import { describe, expect, it } from "vitest";
import { MATERIAL_MAX_LENGTH, materialText } from "./material";

describe("materialText", () => {
  it("keeps a real fabric name as the owner typed it", () => {
    expect(materialText("قطن")).toBe("قطن");
    expect(materialText("Cotton Twill")).toBe("Cotton Twill");
  });

  it("trims the edges only, never the inside", () => {
    expect(materialText("  قطن مصري  ")).toBe("قطن مصري");
    expect(materialText("\tكتان\n")).toBe("كتان");
  });

  it("a missing value is blank, so nothing is sent", () => {
    expect(materialText(null)).toBe("");
    expect(materialText(undefined)).toBe("");
    expect(materialText()).toBe("");
  });

  it("blank text is blank, not a material named ' '", () => {
    expect(materialText("")).toBe("");
    expect(materialText("   ")).toBe("");
    expect(materialText("\n\t ")).toBe("");
  });

  it("never hands back the text 'null' or 'undefined', however it arrives", () => {
    expect(materialText("null")).toBe("");
    expect(materialText(" null ")).toBe("");
    expect(materialText("NULL")).toBe("");
    expect(materialText("undefined")).toBe("");
    expect(materialText(String(null))).toBe("");
    expect(materialText(String(undefined))).toBe("");
  });

  it("a name that merely contains 'null' is a real name and is kept", () => {
    expect(materialText("nullen")).toBe("nullen");
    expect(materialText("Null & Void")).toBe("Null & Void");
  });

  it("does not throw on a number or an object, it just says it as text", () => {
    expect(materialText(0)).toBe("0");
    expect(materialText(100)).toBe("100");
    expect(() => materialText({})).not.toThrow();
  });

  it("the server's limit is 60, and it is exported for the form to use", () => {
    expect(MATERIAL_MAX_LENGTH).toBe(60);
    expect(materialText("ق".repeat(60))).toHaveLength(60);
  });
});
