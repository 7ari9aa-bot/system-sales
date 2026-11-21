import { describe, expect, it } from "vitest";
import { friendlyMetaError } from "./ChannelsSettings";

describe("friendlyMetaError", () => {
  it("tells the owner a Meta outage is not a setup problem", () => {
    const ar = friendlyMetaError("meta_unavailable:Meta is temporarily unavailable (code exchange).", true);
    const en = friendlyMetaError("meta_unavailable:Meta is temporarily unavailable (code exchange).", false);
    expect(ar).toContain("ليست مشكلة في الإعدادات");
    expect(en).toContain("not a setup problem");
    expect(ar).not.toContain("تحقق من إعدادات التطبيق");
    expect(en).not.toContain("Check the app settings");
  });

  it("still sends a genuinely rejected code to the app settings", () => {
    expect(friendlyMetaError("meta_exchange_failed:ValueError", false)).toContain("Check the app settings");
  });
});
