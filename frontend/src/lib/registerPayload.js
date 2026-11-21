/**
 * The body of POST /auth/register. An email and a password alone send exactly what they always
 * sent; the shop name, the country and the terms are added only when the person filled them in.
 * A blank shop name is not sent, and the terms are sent only when the box was ticked, so an old
 * server and a server that reads the new fields both get a payload they accept.
 */

/** The markets the platform serves today (backend: launch_status "live"). */
export const COUNTRIES = Object.freeze([
  { code: "EG", ar: "مصر", en: "Egypt" },
  { code: "SA", ar: "السعودية", en: "Saudi Arabia" },
]);

export function registerPayload({ email, password, captchaToken, shopName, country, terms }) {
  const body = { email, password };
  if (captchaToken) body.captcha_token = captchaToken;
  const name = typeof shopName === "string" ? shopName.trim() : "";
  if (name) body.shop_name = name;
  if (typeof country === "string" && COUNTRIES.some((c) => c.code === country)) body.country_code = country;
  if (terms === true) body.terms_accepted = true;
  return body;
}
