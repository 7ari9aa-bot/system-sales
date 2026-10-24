import { describe, expect, it } from "vitest";
import { gateMessage } from "./WorkingSessionGate";

describe("gateMessage", () => {
  it.each([
    ["needs_setup", "لم يتم تجهيز الكاشير"],
    ["forbidden", "ليست لديك صلاحية"],
    ["unauthorized", "انتهت الجلسة"],
  ])("%s", (status, text) => expect(gateMessage({ status })).toContain(text));

  it("an error shows the server's own message, with a fallback", () => {
    expect(gateMessage({ status: "error", message: "الخادم لا يستجيب" })).toBe("الخادم لا يستجيب");
    expect(gateMessage({ status: "error" })).toBe("تعذّر تحميل الكاشير.");
    expect(gateMessage(undefined)).toBe("تعذّر تحميل الكاشير.");
  });
});

describe("the start-of-day gate", () => {
  it("exports the opening-balance screen the sales, returns and exchange screens depend on", async () => {
    const mod = await import("./WorkingSessionGate");
    expect(typeof mod.StartDay).toBe("function");
    expect(typeof mod.default).toBe("function");
  });
});
