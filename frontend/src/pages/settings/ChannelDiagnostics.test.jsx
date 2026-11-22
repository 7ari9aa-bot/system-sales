import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

import ChannelDiagnostics, {
  DiagnosticsReport,
  checkLabel,
  hasDiagnostics,
  metaErrorLine,
  sortChecks,
} from "@/pages/settings/ChannelDiagnostics";

const report = (checks) => ({ provider: "messenger", state: "error", checks });

describe("who gets a diagnostics button", () => {
  it("is a Meta channel with a saved connection", () => {
    for (const id of ["messenger", "facebook", "instagram", "whatsapp"]) {
      expect(hasDiagnostics({ id, integrationId: "i-1" })).toBe(true);
    }
  });
  it("is nobody else, and nobody without a connection", () => {
    expect(hasDiagnostics({ id: "telegram", integrationId: "i-1" })).toBe(false);
    expect(hasDiagnostics({ id: "webchat", integrationId: "i-1" })).toBe(false);
    expect(hasDiagnostics({ id: "messenger" })).toBe(false);
    expect(hasDiagnostics(null)).toBe(false);
  });
  it("renders nothing for a channel that cannot be diagnosed", () => {
    const out = renderToStaticMarkup(<ChannelDiagnostics channel={{ id: "telegram", integrationId: "i" }} isAr={false} />);
    expect(out).toBe("");
  });
  it("offers the check in the owner's language, without calling Meta on render", async () => {
    const { api } = await import("@/lib/api");
    const en = renderToStaticMarkup(<ChannelDiagnostics channel={{ id: "messenger", integrationId: "i" }} isAr={false} />);
    const ar = renderToStaticMarkup(<ChannelDiagnostics channel={{ id: "messenger", integrationId: "i" }} isAr />);
    expect(en).toContain("Diagnose channel");
    expect(ar).toContain("تشخيص القناة");
    expect(api).not.toHaveBeenCalled();
  });
});

describe("the order of the checks", () => {
  it("puts what is broken first and keeps the order among equals", () => {
    const sorted = sortChecks([
      { key: "a", status: "ok" },
      { key: "b", status: "warning" },
      { key: "c", status: "error" },
      { key: "d", status: "ok" },
      { key: "e", status: "error" },
      { key: "f", status: "unknown" },
    ]);
    expect(sorted.map((c) => c.key)).toEqual(["c", "e", "b", "f", "a", "d"]);
  });
  it("copes with nothing", () => {
    expect(sortChecks(undefined)).toEqual([]);
    expect(sortChecks(null)).toEqual([]);
  });
  it("does not change the list it was given", () => {
    const input = [{ key: "a", status: "ok" }, { key: "b", status: "error" }];
    sortChecks(input);
    expect(input.map((c) => c.key)).toEqual(["a", "b"]);
  });
});

describe("labels and Meta's error line", () => {
  it("names each known check in both languages", () => {
    expect(checkLabel("permissions", false)).toBe("Permissions");
    expect(checkLabel("permissions", true)).toBe("الصلاحيات");
  });
  it("never shows a blank for a check it has not heard of", () => {
    expect(checkLabel("brand_new_check", false)).toBe("brand_new_check");
  });
  it("prints Meta's code, subcode and text the way support asks for them", () => {
    expect(metaErrorLine({ code: 200, subcode: 33, message: "denied" })).toBe("code 200/33 · denied");
    expect(metaErrorLine({ code: 190 })).toBe("code 190");
    expect(metaErrorLine({ message: "only text" })).toBe("only text");
    expect(metaErrorLine(null)).toBe("");
    expect(metaErrorLine("nope")).toBe("");
  });
});

describe("the report", () => {
  const checks = [
    { key: "connection", status: "ok", summary: "The channel is connected." },
    {
      key: "dashboard_webhook",
      status: "warning",
      summary: "No event has ever arrived.",
      action: "Set the callback in the Meta app dashboard.",
      detail: { callback_url: "https://api.example.com/api/v1/webhooks/meta/page", fields: ["messages", "feed"] },
    },
    {
      key: "asset_subscription",
      status: "error",
      summary: "Meta refused.",
      detail: { meta: { code: 200, message: "no permission" } },
    },
  ];
  const html = (isAr = false) => renderToStaticMarkup(<DiagnosticsReport report={report(checks)} isAr={isAr} />);

  it("lists every check with its status, worst first", () => {
    const out = html();
    expect(out).toContain('data-status="error"');
    expect(out.indexOf('data-status="error"')).toBeLessThan(out.indexOf('data-status="warning"'));
    expect(out.indexOf('data-status="warning"')).toBeLessThan(out.indexOf('data-status="ok"'));
  });
  it("tells the owner what to do and where", () => {
    const out = html();
    expect(out).toContain("Set the callback in the Meta app dashboard.");
    expect(out).toContain("https://api.example.com/api/v1/webhooks/meta/page");
    expect(out).toContain("messages, feed");
    expect(out).toContain("code 200 · no permission");
  });
  it("speaks Arabic", () => {
    const out = html(true);
    expect(out).toContain("الاتصال");
    expect(out).toContain("رابط الـCallback");
  });
  it("shows text from Meta as text, never as markup", () => {
    const out = renderToStaticMarkup(
      <DiagnosticsReport
        report={report([{ key: "x", status: "error", summary: "<img src=x onerror=alert(1)>", detail: { last_error: "<script>1</script>" } }])}
        isAr={false}
      />
    );
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<script>");
    expect(out).toContain("&lt;img");
  });
  it("shows nothing when there is no report", () => {
    expect(renderToStaticMarkup(<DiagnosticsReport report={null} isAr={false} />)).toBe("");
  });
});
