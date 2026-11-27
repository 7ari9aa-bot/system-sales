import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CapabilityList } from "./ChannelDiagnostics";
import { capabilityNotice, sortCapabilities, stateLabel } from "@/lib/capabilityStates";

const html = (caps, isAr = true) =>
  renderToStaticMarkup(<CapabilityList capabilities={caps} isAr={isAr} />);

describe("a capability that is not available is explained, not shown as a dead button", () => {
  it("an ineligible capability renders with its reason", () => {
    const out = html([
      { key: "calls", state: "region_restricted", reason: "المكالمات مش متاحة في مصر" },
      { key: "inbox", state: "available" },
    ]);
    expect(out).toContain('data-capability="calls"');
    expect(out).toContain('data-state="region_restricted"');
    expect(out).toContain("ممنوع في بلدك");
    expect(out).toContain("المكالمات مش متاحة في مصر");
  });

  it("an available capability renders normally, with no reason line", () => {
    const out = html([{ key: "inbox", state: "available" }]);
    expect(out).toContain('data-state="available"');
    expect(out).toContain("متاح");
  });

  it("what is broken leads the list, and what works comes last", () => {
    const sorted = sortCapabilities([
      { key: "inbox", state: "available" },
      { key: "flows", state: "not_implemented" },
      { key: "handover", state: "dashboard_field_missing" },
    ]);
    expect(sorted.map((c) => c.key)).toEqual(["handover", "flows", "inbox"]);
  });
});

describe("a control asks the registry before it is enabled", () => {
  it("refuses when the capability is missing from the report", () => {
    const notice = capabilityNotice([{ key: "inbox", state: "available" }], "flows", true);
    expect(notice.enabled).toBe(false);
    expect(notice.known).toBe(false);
    expect(notice.reason).toContain("لا يوجد تقرير");
  });

  it("refuses a capability that needs a dashboard field, and says which state", () => {
    const notice = capabilityNotice(
      [{ key: "staff_reply_sync", state: "dashboard_field_missing", reason: "فعّل message_echoes" }],
      "staff_reply_sync",
      true,
    );
    expect(notice.enabled).toBe(false);
    expect(notice.label).toBe("الحقل غير مفعّل في لوحة Meta");
    expect(notice.reason).toBe("فعّل message_echoes");
  });

  it("allows only an available capability", () => {
    const notice = capabilityNotice([{ key: "posts", state: "available" }], "posts", true);
    expect(notice.enabled).toBe(true);
    expect(notice.reason).toBe("");
  });

  it("never renders an unknown state blank", () => {
    expect(stateLabel("some_new_state", true)).toBe("some_new_state");
    expect(stateLabel("not_implemented", false)).toBe("Not built yet");
  });
});
