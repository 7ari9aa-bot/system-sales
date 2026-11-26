import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TeamField, buildChanges, describeResult, roleLabel } from "./TeamPolicyCard";

const base = { domain: "team", label_ar: "الحقل", description_ar: "وصف", label_en: "Field" };
const draw = (def, value) => renderToStaticMarkup(<TeamField def={def} value={value} isAr onChange={() => {}} />);

describe("team policies card", () => {
  it("the default role is a dropdown of exactly the three roles the server accepts", () => {
    const html = draw(
      { ...base, key: "team.default_role", type: "enum", default: "cashier", allowed_values: ["cashier", "manager", "admin"] },
      "manager",
    );
    expect(html).toContain("<select");
    expect(html).toContain("كاشير");
    expect(html).toContain("مدير");
    expect(html).toContain("مسؤول");
    expect(html).toMatch(/<option value="manager" selected/);
  });

  it("2FA and invites are switches that report their real state", () => {
    const on = draw({ ...base, key: "team.require_2fa", type: "bool", default: false }, true);
    const off = draw({ ...base, key: "team.allow_member_invites", type: "bool", default: true }, false);
    expect(on).toContain('role="switch"');
    expect(on).toContain('aria-checked="true"');
    expect(off).toContain('aria-checked="false"');
  });

  it("the session timeout is a number box carrying the registry's own limits", () => {
    const html = draw(
      { ...base, key: "team.session_timeout_minutes", type: "number", default: 0, min_value: 0, max_value: 10080 },
      0,
    );
    expect(html).toContain('type="number"');
    expect(html).toContain('max="10080"');
    expect(html).toContain('value="0"');
  });

  it("only keys the user changed are written", () => {
    const original = {
      "team.default_role": "cashier",
      "team.require_2fa": false,
      "team.session_timeout_minutes": 0,
      "team.allow_member_invites": true,
    };
    expect(buildChanges(original, original)).toEqual({});
    expect(buildChanges({ ...original, "team.session_timeout_minutes": 480 }, original)).toEqual({
      "team.session_timeout_minutes": 480,
    });
    expect(
      buildChanges({ ...original, "team.require_2fa": true, "team.default_role": "manager" }, original),
    ).toEqual({ "team.require_2fa": true, "team.default_role": "manager" });
  });

  it("a key held for approval is reported as pending, never as saved", () => {
    const pending = describeResult({ applied_changes: {}, pending_approval: ["team.require_2fa"] }, true);
    expect(pending.notice).toBe("");
    expect(pending.error).toContain("team.require_2fa");
    expect(pending.pending).toEqual(["team.require_2fa"]);

    const saved = describeResult({ applied_changes: { "team.default_role": "admin" } }, true);
    expect(saved.notice).toBe("تم الحفظ");
    expect(saved.error).toBe("");
  });

  it("an unknown role prints as itself instead of crashing the row", () => {
    expect(roleLabel("cashier", false)).toBe("Cashier");
    expect(roleLabel("owner", false)).toBe("owner");
  });
});
