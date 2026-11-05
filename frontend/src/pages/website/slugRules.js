/** Site-address (slug) rules — mirrored from the server's
 *  backend/app/modules/website/slugs.py so the purchase form can reject
 *  bad values before the request, with the SAME verdicts: length, charset,
 *  reserved names. The server stays the authority; this is a courtesy. */

export const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?$/;
export const SLUG_MIN_LENGTH = 3;
export const SLUG_MAX_LENGTH = 80;

export const RESERVED_SLUGS = new Set([
  "www", "api", "app", "admin", "owner", "console", "dashboard", "mail",
  "webmail", "smtp", "ftp", "ns1", "ns2", "blog", "shop", "store", "sites",
  "static", "cdn", "assets", "media", "help", "support", "status", "billing",
  "docs", "auth", "login", "signup", "register", "payments", "pay", "security",
  "privacy", "terms", "about", "contact",
]);

/** latin-only slugify (same deferral as the server: no Arabic transliteration) */
export function slugify(raw) {
  const ascii = String(raw ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .toLowerCase()
    .replace(/^-+|-+$/g, "");
  return ascii.slice(0, SLUG_MAX_LENGTH).replace(/-+$/g, "");
}

/** @returns {string | null} an error key, or null when the slug is acceptable */
export function slugError(slug) {
  const s = String(slug ?? "");
  if (!SLUG_RE.test(s)) return "format";
  if (s.length < SLUG_MIN_LENGTH) return "short";
  if (RESERVED_SLUGS.has(s)) return "reserved";
  return null;
}
