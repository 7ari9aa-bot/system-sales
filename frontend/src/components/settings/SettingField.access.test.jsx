import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { SettingsAccessContext } from "@/components/settings/SettingsAccessContext";
import { SettingField } from "@/components/settings/SettingField";

/**
 * A field this member cannot save must not look editable.
 *
 * The registry says which permission owns each key. A manager holds `settings:read` and not
 * `settings:write` (scripts/provision.py ROLE_MATRIX), so before this the value looked
 * editable, the manager typed it, and the save came back 403 — the audit's "managers can edit
 * org settings they cannot save".
 */
const DEF = {
  key: "business.phone",
  type: "string",
  label_ar: "هاتف النشاط",
  label_en: "Business phone",
  description_ar: "",
  description_en: "",
  permission: "settings:write",
  apply_mode: "validated",
  enforced: true,
};

const withAccess = (grant, defn = DEF) =>
  renderToStaticMarkup(
    <I18nProvider>
      <SettingsAccessContext.Provider
        value={{
          access: null,
          loading: false,
          failed: false,
          can: (permission) => (grant === null ? null : grant.includes(permission)),
          canWrite: grant === null ? null : grant.includes("settings:write"),
          canSee: () => true,
        }}
      >
        <SettingField defn={defn} value="0100" onChange={() => {}} isAr={false} />
      </SettingsAccessContext.Provider>
    </I18nProvider>
  );

/** The control itself is disabled — not merely carrying Tailwind's `disabled:` classes. */
const controlDisabled = (html) => /<input[^>]*\sdisabled(?=[\s/>=])/.test(html);

describe("SettingField under a grant", () => {
  test("a writer gets an editable control", () => {
    const html = withAccess(["settings:read", "settings:write"]);
    expect(html).not.toContain("Read-only");
    expect(controlDisabled(html)).toBe(false);
  });

  test("a reader gets the value, a disabled control and the reason", () => {
    const html = withAccess(["settings:read"]);
    expect(html).toContain("Read-only");
    expect(controlDisabled(html)).toBe(true);
    // The value is still shown: reading is what the grant allows.
    expect(html).toContain('value="0100"');
  });

  test("a key owned by another permission follows THAT permission", () => {
    // `settings:branch_write` owns a branch's own keys: a manager holds it and may edit them
    // even though shop-wide writes are refused.
    const branchDef = { ...DEF, permission: "settings:branch_write" };
    expect(withAccess(["settings:read", "settings:branch_write"], branchDef)).not.toContain(
      "Read-only"
    );
    expect(withAccess(["settings:read"], branchDef)).toContain("Read-only");
  });

  test("an unknown grant does not disable the control on a guess", () => {
    // While /roles/me is in flight the field stays usable; the server's 403 is the real rule.
    expect(withAccess(null)).not.toContain("Read-only");
  });
});
