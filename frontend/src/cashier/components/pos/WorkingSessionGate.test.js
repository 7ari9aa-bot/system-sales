import { describe, expect, it } from "vitest";
import { cn } from "@/cashier/lib/utils";
import { buttonVariants } from "@/cashier/components/ui/button";
import { gateMessage, setupAction, startButtonLook, startDayParts, tillLabel } from "./WorkingSessionGate";

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

describe("startDayParts", () => {
  it("the closing dot travels with the till name so it cannot sit on its own line", () => {
    const { lead, tail } = startDayParts({ name: "Main till" });
    expect(tail).toBe(" (الدرج الرئيسي).");
    expect(lead.endsWith(".")).toBe(false);
  });

  it("a till with no name still ends the sentence with a dot", () => {
    expect(startDayParts({}).tail).toBe(".");
    expect(startDayParts(null).tail).toBe(".");
  });

  it("a name the owner typed is kept inside the brackets", () => {
    expect(startDayParts({ name: "درج الدور الأول" }).tail).toBe(" (درج الدور الأول).");
  });
});

describe("startButtonLook", () => {
  it("while waiting for the number the button keeps a visible fill, border and text colour", () => {
    const { className } = startButtonLook(true);
    expect(className).toContain("bg-orange-100");
    expect(className).toContain("border-orange-300");
    expect(className).toContain("text-orange-800");
    expect(className).toContain("disabled:opacity-100");
  });

  it("once it can be pressed it uses the normal primary look, with no waiting colours", () => {
    const { className } = startButtonLook(false);
    expect(className).toBe("w-full");
    expect(className).not.toContain("orange");
  });
});

describe("the waiting start button after the real class merge", () => {
  const merged = (waiting) =>
    cn(buttonVariants({ className: startButtonLook(waiting).className })).split(/\s+/);

  it("loses the half-faded base look and the primary fill, so it is not washed out", () => {
    const c = merged(true);
    expect(c).not.toContain("disabled:opacity-50");
    expect(c).not.toContain("bg-primary");
    expect(c).toContain("bg-orange-100");
    expect(c).toContain("disabled:opacity-100");
  });

  it("when it can be pressed it keeps the normal primary look and the base fade rule", () => {
    const c = merged(false);
    expect(c).toContain("bg-primary");
    expect(c).toContain("disabled:opacity-50");
  });
});
