/**
 * How a shift is closed, built to the rules the server enforces (pos/service.py::close_session and
 * pos/tender.py::check_close_variance). The server decides; this only keeps an obviously wrong close
 * from being sent and tells the cashier what is still missing.
 *
 *  - A till that does not take payments has no drawer: nothing is counted and nothing is sent.
 *  - A till that does needs the counted cash. The gap is counted minus expected, in whole cents.
 *  - A gap needs its reason when the owner requires one (`pos.variance_reason_required`).
 *  - A gap above the owner's limit needs a manager; a limit of 0 means no limit.
 *
 * Money is compared in integer cents, never as floats.
 */
import { fromMinor, isWireMoney, toMinor, toWire } from "./money";

const REASON_MAX = 500;

/** True when this till counts a drawer at close. */
export const countsDrawer = (rules) => Boolean(rules?.take_payments);

/** counted - expected, in cents, or null while either is unknown or the count is not a valid amount. */
export function gapMinor(counted, expected) {
  if (counted === "" || counted == null || expected == null) return null;
  try {
    const c = toMinor(String(counted));
    if (c < 0) return null;
    return c - toMinor(expected);
  } catch {
    return null;
  }
}

/** What the screen still needs from the cashier before the close can be sent. Empty list = ready. */
export function closeProblems({ rules, counted, expected, reason, reasonRequired = true, threshold = 0, canApprove = false }) {
  if (!countsDrawer(rules)) return [];
  const problems = [];
  const gap = gapMinor(counted, expected);
  if (counted === "" || counted == null) return ["count"];
  if (gap === null) return ["count"];
  if (gap === 0) return problems;
  const text = String(reason ?? "").trim();
  if (reasonRequired && !text) problems.push("reason");
  if (text.length > REASON_MAX) problems.push("reason_too_long");
  const limit = threshold > 0 ? toMinor(String(threshold)) : 0;
  if (limit > 0 && Math.abs(gap) > limit && !canApprove) problems.push("approval");
  return problems;
}

/** The body of the close request: nothing for a till with no drawer, otherwise the count and the reason (if any gap). */
export function closeBody({ rules, counted, expected, reason }) {
  if (!countsDrawer(rules)) return undefined;
  const body = { counted_cash: toWire(String(counted)) };
  const gap = gapMinor(counted, expected);
  const text = String(reason ?? "").trim();
  if (gap !== 0 && text) body.variance_reason = text;
  return body;
}

/** Signed gap as text for the screen ("-20.00" short, "5.00" over) or null. */
export function gapText(counted, expected) {
  const g = gapMinor(counted, expected);
  return g === null ? null : fromMinor(g);
}

export { isWireMoney };
