// @vitest-environment node
import { describe, expect, it } from "vitest";

/**
 * Two things the one-click WhatsApp connect got wrong for a slow or Arabic-speaking owner:
 *  - Meta's one-time code lives about five minutes, but the connect waited ten for the signup
 *    window's report, so a lingering owner held a dead code (W2);
 *  - the Facebook SDK was always loaded in English, so Meta's permission dialogs were English
 *    even for an Arabic owner (W15).
 */
describe("how long the signup code may wait for the report", () => {
  const load = () => import("./ChannelsSettings.jsx");

  it("gives up inside the code's five-minute life", async () => {
    const { SIGNUP_REPORT_WAIT_MS } = await load();
    expect(SIGNUP_REPORT_WAIT_MS).toBeGreaterThan(0);
    expect(SIGNUP_REPORT_WAIT_MS).toBeLessThan(5 * 60 * 1000);
  });

  it("lets the whole window run longer than the code's wait", async () => {
    const { SIGNUP_WINDOW_MS, SIGNUP_REPORT_WAIT_MS } = await load();
    expect(SIGNUP_WINDOW_MS).toBeGreaterThan(SIGNUP_REPORT_WAIT_MS);
  });

  it.each([
    [true, /[\u0600-\u06FF]/],
    [false, /expired/i],
  ])("explains what happened and what to do (isAr=%s)", async (isAr, pattern) => {
    const { signupCodeExpiredError } = await load();
    const error = signupCodeExpiredError(isAr);
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toMatch(pattern);
  });

  it("does not blame Meta's refusal, which is what the server used to say", async () => {
    const { signupCodeExpiredError } = await load();
    expect(signupCodeExpiredError(false).message).not.toMatch(/rejected/i);
  });
});

describe("the Facebook SDK language", () => {
  const load = () => import("./ChannelsSettings.jsx");

  it("is Arabic for an Arabic owner", async () => {
    const { facebookSdkUrl } = await load();
    expect(facebookSdkUrl(true)).toBe("https://connect.facebook.net/ar_AR/sdk.js");
  });

  it("is English otherwise", async () => {
    const { facebookSdkUrl } = await load();
    expect(facebookSdkUrl(false)).toBe("https://connect.facebook.net/en_US/sdk.js");
  });

  it("always comes from Meta's own host over HTTPS", async () => {
    const { facebookSdkUrl } = await load();
    for (const isAr of [true, false]) {
      const url = new URL(facebookSdkUrl(isAr));
      expect(url.protocol).toBe("https:");
      expect(url.hostname).toBe("connect.facebook.net");
    }
  });
});
