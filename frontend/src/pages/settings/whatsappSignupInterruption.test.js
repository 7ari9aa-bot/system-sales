// @vitest-environment node
import { describe, expect, it } from "vitest";

/**
 * Meta's signup window reports CANCEL (the owner left) and ERROR (Meta refused). Both used to show
 * "cancelled", which hid Meta's reason and the ids support needs to look the failure up.
 */
describe("whatsappSignupInterruption", () => {
  const load = async () => (await import("./ChannelsSettings.jsx")).whatsappSignupInterruption;

  it("shows Meta's own reason and ids for an ERROR", async () => {
    const fn = await load();
    const error = fn(
      { event: "ERROR", data: { error_message: "Phone number is blocked", error_id: "1234", session_id: "s-9" } },
      false
    );
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toContain("Phone number is blocked");
    expect(error.message).toContain("1234");
    expect(error.message).toContain("s-9");
    expect(error.message).not.toMatch(/cancel/i);
  });

  it("is in Arabic for an Arabic owner", async () => {
    const fn = await load();
    const error = fn({ event: "ERROR", data: { error_message: "x" } }, true);
    expect(error.message).toMatch(/[\u0600-\u06FF]/);
  });

  it("says so when Meta gave no reason, instead of inventing one", async () => {
    const fn = await load();
    expect(fn({ event: "ERROR", data: {} }, false).message).toContain("no reason");
    expect(fn({ event: "ERROR" }, false).message).toContain("no reason");
  });

  it("names the step the owner left on for a CANCEL", async () => {
    const fn = await load();
    const error = fn({ event: "CANCEL", data: { current_step: "PHONE_NUMBER_SETUP" } }, false);
    expect(error.message).toContain("PHONE_NUMBER_SETUP");
    expect(error.message).not.toMatch(/Meta could not/);
  });

  it("still answers a CANCEL that names no step", async () => {
    const fn = await load();
    for (const isAr of [true, false]) {
      expect(fn({ event: "CANCEL" }, isAr).message.length).toBeGreaterThan(15);
      expect(fn({ event: "CANCEL", data: null }, isAr).message.length).toBeGreaterThan(15);
    }
  });

  it("treats a CANCEL and an ERROR differently", async () => {
    const fn = await load();
    expect(fn({ event: "CANCEL" }, false).message).not.toEqual(fn({ event: "ERROR" }, false).message);
  });

  it("ignores values that are not plain text", async () => {
    const fn = await load();
    const error = fn({ event: "ERROR", data: { error_message: { evil: 1 }, error_id: ["x"] } }, false);
    expect(error.message).not.toContain("[object Object]");
  });
});
