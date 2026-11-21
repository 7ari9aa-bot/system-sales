import { describe, expect, it } from "vitest";
import { COUNTRIES, registerPayload } from "./registerPayload";

const base = { email: "a@b.dev", password: "pw-123456" };

describe("the old signup is unchanged", () => {
  it("an email and a password send exactly those two", () => {
    expect(registerPayload(base)).toEqual({ email: "a@b.dev", password: "pw-123456" });
  });
  it("without a captcha token the key is absent, not undefined", () => {
    expect("captcha_token" in registerPayload(base)).toBe(false);
    expect("captcha_token" in registerPayload({ ...base, captchaToken: "" })).toBe(false);
    expect("captcha_token" in registerPayload({ ...base, captchaToken: null })).toBe(false);
  });
  it("with a captcha token it adds only the token", () => {
    expect(registerPayload({ ...base, captchaToken: "t" })).toEqual({ ...base, captcha_token: "t" });
  });
  it("blank extras add nothing", () => {
    expect(
      registerPayload({ ...base, shopName: "   ", country: "", terms: false }),
    ).toEqual(base);
    expect(registerPayload({ ...base, shopName: undefined, country: undefined, terms: undefined })).toEqual(base);
  });
});

describe("the new fields", () => {
  it("the shop name is trimmed and sent", () => {
    expect(registerPayload({ ...base, shopName: "  محل نور " }).shop_name).toBe("محل نور");
  });
  it("a served country is sent", () => {
    expect(registerPayload({ ...base, country: "SA" }).country_code).toBe("SA");
    expect(registerPayload({ ...base, country: "EG" }).country_code).toBe("EG");
  });
  it.each(["AE", "QA", "US", "eg", "", "EGY", null, 5])("a country we do not serve (%s) is never sent", (c) => {
    expect("country_code" in registerPayload({ ...base, country: c })).toBe(false);
  });
  it("the terms are sent only when ticked", () => {
    expect(registerPayload({ ...base, terms: true }).terms_accepted).toBe(true);
    for (const t of [false, undefined, null, "true", 1]) {
      expect("terms_accepted" in registerPayload({ ...base, terms: t })).toBe(false);
    }
  });
  it("the list is exactly the two live markets", () => {
    expect(COUNTRIES.map((c) => c.code)).toEqual(["EG", "SA"]);
  });
});
