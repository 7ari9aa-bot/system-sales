import { describe, expect, it } from "vitest";

import { whatsappConnectedNotice } from "./ChannelsSettings.jsx";

/**
 * The connect notice is the only place the shop learns WHICH way its number was connected.
 *
 * The server derives `onboarding_mode` from Meta's own answer (`is_on_biz_app` +
 * `platform_type`), so a plain "connected" line would be a promise the channel cannot keep when
 * the number turned out to be Cloud-API-only: replies typed in the phone app never reach FIHRIST
 * in that case, and the whole point of coexistence is that they do.
 */
describe("whatsappConnectedNotice", () => {
  it("promises mirrored app replies only when Meta verified coexistence", () => {
    const en = whatsappConnectedNotice(
      { onboarding_mode: "coexistence", coexistence_status: "verified" },
      false,
    );
    expect(en).toMatch(/phone app keeps working/i);
    expect(en).toMatch(/human messages/i);
    const ar = whatsappConnectedNotice(
      { onboarding_mode: "coexistence", coexistence_status: "verified" },
      true,
    );
    expect(ar).toMatch(/على الهاتف/);
  });

  it("says the phone app is NOT mirrored when the number is Cloud API only", () => {
    const en = whatsappConnectedNotice(
      { onboarding_mode: "cloud_api", coexistence_status: "not_on_business_app" },
      false,
    );
    expect(en).toMatch(/not on the WhatsApp Business app/i);
    expect(en).toMatch(/will not appear here/i);
    const ar = whatsappConnectedNotice(
      { onboarding_mode: "cloud_api", coexistence_status: "not_on_business_app" },
      true,
    );
    expect(ar).toMatch(/غير مسجل على تطبيق WhatsApp Business/);
  });

  it("falls back to the plain success line for an older server answer", () => {
    expect(whatsappConnectedNotice({}, false)).toMatch(/connected/i);
    expect(whatsappConnectedNotice(undefined, true)).toMatch(/تم ربط/);
  });
});
