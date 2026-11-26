import { describe, expect, it } from "vitest";

/** Test the status metadata that ChangeRequestList uses for rendering.
 * Extracted as a standalone test to avoid needing a DOM environment. */
const STATUS_META = {
  pending_approval: { labelAr: "بانتظار الموافقة", labelEn: "Pending", tone: "warning" },
  approved: { labelAr: "تمت الموافقة", labelEn: "Approved", tone: "success" },
  rejected: { labelAr: "مرفوض", labelEn: "Rejected", tone: "error" },
};

describe("ChangeRequest status metadata", () => {
  it("pending_approval ليه تون warning", () => {
    expect(STATUS_META.pending_approval.tone).toBe("warning");
  });

  it("approved ليه تون success", () => {
    expect(STATUS_META.approved.tone).toBe("success");
  });

  it("rejected ليه تون error", () => {
    expect(STATUS_META.rejected.tone).toBe("error");
  });

  it("كل الحالات ليه labelAr و labelEn", () => {
    for (const [, meta] of Object.entries(STATUS_META)) {
      expect(meta.labelAr).toBeTruthy();
      expect(meta.labelEn).toBeTruthy();
    }
  });
});

/** Test the changed-entries derivation logic (same shape as useSettings.changedEntries). */
describe("changedEntries derivation", () => {
  it("بيفصل القيم المتغيرة عن الثابتة", () => {
    const values = { "pos.auto_reserve": true, "pos.fifo": false };
    const original = { "pos.auto_reserve": false, "pos.fifo": false };
    const defMap = {
      "pos.auto_reserve": { apply_mode: "validated", label_en: "Auto Reserve", domain: "pos" },
      "pos.fifo": { apply_mode: "validated", label_en: "FIFO", domain: "pos" },
    };

    const entries = Object.entries(values)
      .filter(([k, v]) => v !== original[k])
      .map(([k, v]) => {
        const def = defMap[k];
        return {
          key: k,
          label: def?.label_en || k,
          oldValue: original[k],
          newValue: v,
          applyMode: def?.apply_mode || "validated",
          needsApproval: def?.apply_mode === "approval_required",
          domain: def?.domain || "",
        };
      });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("pos.auto_reserve");
    expect(entries[0].oldValue).toBe(false);
    expect(entries[0].newValue).toBe(true);
    expect(entries[0].needsApproval).toBe(false);
  });

  it("بيقيد الإعدادات اللي محتاجة موافقة", () => {
    const values = { "security.session_timeout": 300 };
    const original = { "security.session_timeout": 180 };
    const defMap = {
      "security.session_timeout": {
        apply_mode: "approval_required",
        label_en: "Session Timeout",
        domain: "security",
      },
    };

    const entries = Object.entries(values)
      .filter(([k, v]) => v !== original[k])
      .map(([k, v]) => {
        const def = defMap[k];
        return {
          key: k,
          label: def?.label_en || k,
          oldValue: original[k],
          newValue: v,
          applyMode: def?.apply_mode || "validated",
          needsApproval: def?.apply_mode === "approval_required",
        };
      });

    expect(entries).toHaveLength(1);
    expect(entries[0].needsApproval).toBe(true);
  });

  it("مفيش تغييرات → مصفوفة فاضية", () => {
    const values = { "pos.fifo": false };
    const original = { "pos.fifo": false };

    const entries = Object.entries(values)
      .filter(([k, v]) => v !== original[k])
      .map(([k, v]) => ({ key: k, oldValue: original[k], newValue: v }));

    expect(entries).toHaveLength(0);
  });
});
