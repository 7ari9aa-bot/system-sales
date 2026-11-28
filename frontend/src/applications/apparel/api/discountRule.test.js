import { describe, expect, it } from "vitest";
import { discountRefusal } from "./discountRule";

describe("discountRefusal: the shop owner's discount ceiling", () => {
  it("turns the server's refusal into Arabic that names the shop's number", () => {
    const msg = discountRefusal("this discount is above the 20% this shop allows; ask a manager or lower the discount");
    expect(msg).toContain("20%");
    expect(msg).toMatch(/مدير/);
    expect(msg).not.toMatch(/this shop/);
  });
  it("keeps a decimal ceiling exactly as the server said it", () => {
    expect(discountRefusal("this discount is above the 12.50% this shop allows; ask a manager or lower the discount")).toContain("12.50%");
  });
  it("leaves every other message alone, so nothing else is hidden", () => {
    expect(discountRefusal("the day has been closed")).toBe("the day has been closed");
  });
  it("passes an empty or missing message through untouched", () => {
    expect(discountRefusal("")).toBe("");
    expect(discountRefusal(undefined)).toBeUndefined();
  });
});
