/**
 * The request bodies the cashier-settings screen sends for a POS profile, kept pure so the rules the
 * shop owner relies on are tested without rendering the screen.
 *
 * - ``require_customer`` is always sent as a real boolean, so the checkbox is what decides it.
 * - The walk-in customer is the same: on EDIT "none" is sent as ``null`` so the server clears it; sending
 *   nothing would silently keep the old customer.
 * - A blank discount ceiling means two different things: on CREATE it is left out (no ceiling yet);
 *   on EDIT it is sent as ``null`` on purpose, because the owner emptied the field to remove the ceiling.
 */
const blank = (v) => v === null || v === undefined || String(v).trim() === "";

export function createProfileBody(form) {
  return {
    name: form.name,
    code: form.code,
    warehouse_id: form.warehouse_id,
    default_customer_id: form.default_customer_id || undefined,
    default_payment_method: form.default_payment_method,
    allowed_payment_methods: form.allowed_payment_methods,
    require_customer: !!form.require_customer,
    max_discount_pct: blank(form.max_discount_pct) ? undefined : String(form.max_discount_pct).trim(),
  };
}

export function updateProfileBody(p) {
  return {
    name: p.name,
    warehouse_id: p.warehouse_id,
    default_customer_id: p.default_customer_id || null,
    default_payment_method: p.default_payment_method || undefined,
    allowed_payment_methods: p.allowed_payment_methods,
    require_customer: !!p.require_customer,
    max_discount_pct: blank(p.max_discount_pct) ? null : String(p.max_discount_pct).trim(),
  };
}
