/**
 * The branch week the panel sends must be exactly what the branch said.
 *
 * The backend refuses a day that closes before it opens (422) and treats `{}` as "follows the
 * store", so the panel's job is to send a day only when it is complete — closed, or open with both
 * times — and to send nothing at all when the shop has not described any day.
 */
import { describe, expect, it } from "vitest";
import { hoursPayload } from "@/components/settings/BranchPanels";

const blank = () =>
  Object.fromEntries(
    ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => [
      d,
      { closed: false, open: "", close: "" },
    ]),
  );

describe("hoursPayload", () => {
  it("sends a closed day as closed and nothing else", () => {
    const days = blank();
    days.fri = { closed: true, open: "10:00", close: "23:00" };
    expect(hoursPayload(days)).toEqual({ fri: { closed: true } });
  });

  it("sends a trading day with both times", () => {
    const days = blank();
    days.mon = { closed: false, open: "10:00", close: "23:00" };
    expect(hoursPayload(days)).toEqual({ mon: { open: "10:00", close: "23:00" } });
  });

  it("drops a half-filled day instead of inventing the missing time", () => {
    const days = blank();
    days.sat = { closed: false, open: "09:00", close: "" };
    days.sun = { closed: false, open: "", close: "21:00" };
    expect(hoursPayload(days)).toEqual({});
  });

  it("keeps the week in order regardless of the object's key order", () => {
    const days = {
      sun: { closed: false, open: "12:00", close: "20:00" },
      mon: { closed: false, open: "09:00", close: "17:00" },
    };
    expect(Object.keys(hoursPayload(days))).toEqual(["mon", "sun"]);
  });

  it("sends an empty object when nothing is described, which means follows the store", () => {
    expect(hoursPayload(blank())).toEqual({});
  });
});
