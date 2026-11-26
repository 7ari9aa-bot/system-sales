import { describe, expect, it } from "vitest";
import { SCOPE_OPTIONS } from "@/components/settings/useSettings";

describe("SCOPE_OPTIONS", () => {
  it("يحتوي على كل النطاقات من الـ backend Scope enum", () => {
    const values = SCOPE_OPTIONS.map((o) => o.value);
    expect(values).toContain("tenant");
    expect(values).toContain("workspace");
    expect(values).toContain("branch");
    expect(values).toContain("warehouse");
    expect(values).toContain("pos_profile");
    expect(values).toContain("register");
    expect(values).toContain("channel");
    expect(values).toContain("user");
  });

  it("كل خيار ليه labelAr و labelEn", () => {
    for (const opt of SCOPE_OPTIONS) {
      expect(opt.labelAr).toBeTruthy();
      expect(opt.labelEn).toBeTruthy();
    }
  });

  it("مفيش قيم مكررة", () => {
    const values = SCOPE_OPTIONS.map((o) => o.value);
    expect(new Set(values).size).toBe(values.length);
  });
});
