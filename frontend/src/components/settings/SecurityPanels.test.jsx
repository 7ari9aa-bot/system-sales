import { describe, expect, test } from "vitest";
import ar from "@/lib/i18n/ar";
import en from "@/lib/i18n/en";
import { humaniseSeconds } from "./SecurityPanels";

// Section 18's seven pages are read from the source, so the test fails the moment a page is
// added to the tab strip without its two translations — the failure mode the map warns about
// ("keep both languages in step") is otherwise only caught by an Arabic reader.
const SECTION_18_PAGES = [
  "security-policies",
  "session-control",
  "audit-log",
  "settings-change-log",
  "approval-requests",
  "sensitive-settings",
  "emergency-procedures",
];

describe("section 18 copy", () => {
  test("every page has a title and a description in both languages", () => {
    for (const page of SECTION_18_PAGES) {
      for (const [lang, dict] of [
        ["ar", ar],
        ["en", en],
      ]) {
        for (const field of ["title", "desc"]) {
          const key = `settings.security.pages.${page}.${field}`;
          expect(dict[key], `${lang} is missing ${key}`).toBeTruthy();
        }
      }
    }
  });

  test("the panels' own labels exist in both languages", () => {
    const keys = [
      "settings.security.posture.title",
      "settings.security.posture.desc",
      "settings.security.posture.strongPasswords",
      "settings.security.posture.accessTtl",
      "settings.security.posture.refreshTtl",
      "settings.security.posture.allowlist",
      "settings.security.posture.auditRetention",
      "settings.security.posture.keyRotation",
      "settings.security.posture.whereToEdit",
      "settings.security.sensitive.title",
      "settings.security.sensitive.desc",
      "settings.security.sensitive.empty",
      "settings.security.sensitive.approval",
      "settings.security.sensitive.notActive",
      "settings.security.sensitive.whereToEdit",
      "settings.security.restore.title",
      "settings.security.restore.desc",
      "settings.security.restore.warning",
      "settings.security.restore.when",
      "settings.security.restore.reason",
      "settings.security.restore.action",
      "settings.security.restore.done",
      "settings.security.restore.scope",
      "settings.security.approvals.title",
      "settings.security.approvals.desc",
      "settings.security.approvals.empty",
      "settings.security.approvals.whereToEdit",
      "settings.security.auditLog.title",
      "settings.security.auditLog.desc",
      "settings.security.auditLog.empty",
      "settings.security.auditLog.whereToEdit",
      "settings.security.changeLog.title",
      "settings.security.changeLog.desc",
      "settings.security.changeLog.empty",
      "settings.security.changeLog.whereToEdit",
      "settings.nav.governance",
      "settings.group.advanced",
    ];
    for (const key of keys) {
      expect(ar[key], `ar is missing ${key}`).toBeTruthy();
      expect(en[key], `en is missing ${key}`).toBeTruthy();
    }
  });
});

describe("humaniseSeconds", () => {
  test("reads a lifetime the way a person says it", () => {
    expect(humaniseSeconds(1800)).toBe("30 min");
    expect(humaniseSeconds(3600)).toBe("1 hour");
    expect(humaniseSeconds(7200)).toBe("2 hours");
    expect(humaniseSeconds(86400)).toBe("1 day");
    expect(humaniseSeconds(1209600)).toBe("14 days");
  });

  test("an unusable value is a dash, never NaN on the page", () => {
    expect(humaniseSeconds(undefined)).toBe("—");
    expect(humaniseSeconds(0)).toBe("—");
    expect(humaniseSeconds("nope")).toBe("—");
  });
});
