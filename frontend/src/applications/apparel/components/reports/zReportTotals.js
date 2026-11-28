/**
 * Footer totals of the Z report. Movement (invoices, sales, returns, exchange difference) adds up
 * across days. The closing balance does NOT: each day's balance is its own figure, and the sum of
 * several days' balances is not a balance of anything, so it is deliberately absent.
 */
export function zReportTotals(rows) {
  const sum = (key) => +rows.reduce((s, r) => s + (r[key] ?? 0), 0).toFixed(2);
  return {
    invoices: sum("invoices"),
    salesTotal: sum("salesTotal"),
    returnsTotal: sum("returnsTotal"),
    exchangeDifference: sum("exchangeDifference"),
  };
}
