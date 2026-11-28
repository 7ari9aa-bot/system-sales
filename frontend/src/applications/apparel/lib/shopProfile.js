/**
 * What a printed receipt says about the shop. Only facts the system actually has are printed.
 * The backend knows the shop NAME (the signed-in user's tenant); address, phone and tax number are
 * not stored anywhere yet, so they are left out rather than invented. A wrong tax number on a
 * sales document is worse than none. When those fields get a home, pass them in and they print.
 */
export function receiptHeader(tenant, extra = {}) {
  const clean = (v) => (typeof v === "string" ? v.trim() : "");
  return {
    name: clean(tenant?.name) || "المتجر",
    branch: clean(extra.branch),
    phone: clean(extra.phone),
    taxId: clean(extra.taxId),
  };
}
