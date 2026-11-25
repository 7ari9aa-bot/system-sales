import { describe, expect, it } from "vitest";
import { POS_SECTION_SLUGS, resolvePosSection } from "./PosSettings";

// كل قسم في إعدادات نقاط البيع بقى بمساره: الشاشة كانت ٦١٤ سطر و٩ أقسام مكدّسة، فبقى
// كل واحد يفتح لوحده على /settings/pos/<slug> وأي رابط قديم يفتح «بيانات المحل».
describe("أقسام إعدادات نقاط البيع", () => {
  it("كل قسم ليه slug مستقل ومفيش تكرار", () => {
    expect(POS_SECTION_SLUGS).toEqual([
      "shop",
      "policy",
      "einvoice",
      "receipts",
      "print",
      "lists",
      "users",
      "backup",
      "devices",
    ]);
    expect(new Set(POS_SECTION_SLUGS).size).toBe(POS_SECTION_SLUGS.length);
  });

  it("المسار بيرجع القسم بتاعه", () => {
    expect(resolvePosSection("devices").labelKey).toBe("settings.pos.devices");
    expect(resolvePosSection("receipts").value).toBe("receipts");
  });

  it("رابط قديم بلا قسم أو بقسم غلط يفتح بيانات المحل بدل صفحة فاضية", () => {
    expect(resolvePosSection(undefined).value).toBe("shop");
    expect(resolvePosSection("nonsense").value).toBe("shop");
  });
});
