/**
 * What the shop owner decided about its receipt, as the server resolved it.
 *
 * The screen preview and the printed receipt both read this one block, so they cannot disagree and
 * no shop policy is written in the client. The wording that depends on a setting (how many days an
 * exchange is allowed) is built here from the setting's value; nothing is assumed when the server
 * sent nothing.
 */

const text = (v) => (typeof v === "string" ? v.trim() : "");

const PAPER = new Set([58, 80]);

const whole = (v, fallback, low, high) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return fallback;
  return Math.max(low, Math.min(high, Math.trunc(v)));
};

/** The shop block of a receipt, with every field safe to print as given. */
export function receiptShop(raw) {
  const s = raw && typeof raw === "object" ? raw : {};
  return {
    name: text(s.shop_name),
    address: text(s.address),
    phone: text(s.phone),
    taxId: text(s.tax_id),
    paperMm: PAPER.has(s.paper_mm) ? s.paper_mm : 80,
    showLogo: s.show_logo === true,
    headerText: text(s.header_text),
    footerText: text(s.footer_text),
    copies: whole(s.copies, 1, 1, 5),
    showTaxDetail: s.show_tax_detail === true,
    exchangeDays: whole(s.exchange_days, 0, 0, 365),
  };
}

/**
 * The policy line at the foot of a receipt: the owner's own footer, then the exchange promise only
 * when the shop allows exchanges. A shop with exchanges off prints no promise at all.
 */
export function receiptFooterLines(shop) {
  const out = [];
  if (shop.footerText) out.push(shop.footerText);
  if (shop.exchangeDays > 0) {
    out.push(
      shop.exchangeDays === 1
        ? "الاستبدال خلال يوم واحد بشرط وجود الفاتورة"
        : `الاستبدال خلال ${shop.exchangeDays} يومًا بشرط وجود الفاتورة`,
    );
  }
  return out;
}

/** The lines under the shop name: address, phone, tax number, and the owner's header, if any. */
export function receiptHeaderLines(shop) {
  const out = [];
  if (shop.headerText) out.push(shop.headerText);
  if (shop.address) out.push(shop.address);
  if (shop.phone) out.push(shop.phone);
  if (shop.taxId) out.push(`الرقم الضريبي: ${shop.taxId}`);
  return out;
}

/**
 * The short currency sign for an ISO code, as the browser writes it in Arabic ("EGP" -> "ج.م.").
 * No table of currencies lives here: the order carries the code, the browser knows the sign. A code
 * it cannot read is printed as it is, which is honest, rather than guessed.
 */
export function currencyLabel(code) {
  const iso = typeof code === "string" ? code.trim().toUpperCase() : "";
  if (!/^[A-Z]{3}$/.test(iso)) return "";
  try {
    const parts = new Intl.NumberFormat("ar-EG", { style: "currency", currency: iso }).formatToParts(0);
    // The browser ends an abbreviation with a full stop ("ج.م."); the system has always written
    // "ج.م", so the trailing stop goes and no existing amount changes its look.
    const sign = parts.find((p) => p.type === "currency")?.value?.trim().replace(/\.$/, "");
    return sign || iso;
  } catch {
    return iso;
  }
}
