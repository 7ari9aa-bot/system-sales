import { describe, expect, it } from "vitest";
import { gateMessage, setupAction, tillLabel } from "./WorkingSessionGate";

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

describe("first use of a shop: nobody is told to 'ask the manager' when there may be none", () => {
  it("the message says what to do, not who to ask", () => {
    const msg = gateMessage({ status: "needs_setup" });
    expect(msg).toContain("لم يتم تجهيز الكاشير");
    expect(msg).not.toContain("اطلب من المدير");
  });

  it("offers a way forward: set up and start the day from the shifts page", () => {
    expect(setupAction({ status: "needs_setup" })).toEqual({ label: "تجهيز الكاشير وبدء اليوم", to: "/cashier/shifts" });
  });

  it("offers nothing for states that setting up cannot fix", () => {
    expect(setupAction({ status: "forbidden" })).toBeNull();
    expect(setupAction({ status: "unauthorized" })).toBeNull();
    expect(setupAction({ status: "error" })).toBeNull();
    expect(setupAction(undefined)).toBeNull();
  });
});

describe("tillLabel", () => {
  it.each([["Main till"], ["main till"], ["  MAIN TILL  "], ["Main"], ["main"]])(
    "the factory name %j reads as Arabic",
    (name) => expect(tillLabel({ name })).toBe("الدرج الرئيسي"),
  );

  it("a name a person typed is shown exactly as typed", () => {
    expect(tillLabel({ name: "درج الدور الأول" })).toBe("درج الدور الأول");
    expect(tillLabel({ name: "Main till 2" })).toBe("Main till 2");
  });

  it("no till or an empty name shows nothing, never the word undefined", () => {
    expect(tillLabel(null)).toBe("");
    expect(tillLabel(undefined)).toBe("");
    expect(tillLabel({})).toBe("");
    expect(tillLabel({ name: "   " })).toBe("");
    expect(tillLabel({ name: null })).toBe("");
  });
});
