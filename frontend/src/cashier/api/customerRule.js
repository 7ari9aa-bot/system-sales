/**
 * "Does this sale still need a customer?" Kept pure so the till and the tests share ONE rule.
 *
 * A till whose profile sets require_customer refuses a sale with no customer. The server enforces it
 * (400); the screen mirrors it so the cashier is told BEFORE the payment dialog, not after a refusal.
 * The free-text name field is only a label for the receipt: it is NOT a customer, and never satisfies the rule.
 */
export function customerBlock({ requireCustomer, customerId }) {
  if (!requireCustomer) return null;
  return customerId ? null : "هذه الوردية تتطلب اختيار عميل قبل إتمام البيع";
}

/** The customer rows the picker shows: blocked customers cannot be sold to, so they are not offered. */
export function sellableCustomers(rows) {
  return (rows?.items ?? rows ?? []).filter((c) => c && !c.is_blocked);
}
