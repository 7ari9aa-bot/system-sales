import { toMinor } from "./money";

/**
 * Runs async work but delivers only the result of the most recent call. Used for /quote: while
 * the cashier keeps editing the cart, an earlier slower answer must not replace the total of the
 * cart as it is now. `run.cancel()` also drops anything still pending.
 */
export function latestOnly(onResult, onError = () => {}) {
  let seq = 0;
  const run = (work) => {
    const mine = ++seq;
    return Promise.resolve()
      .then(work)
      .then((v) => mine === seq && onResult(v))
      .catch((e) => mine === seq && onError(e));
  };
  run.cancel = () => {
    seq += 1;
  };
  return run;
}

/** Line percentage discounts + the invoice amount, as integer cents. */
export function discountMinor(lines, invoiceAmount) {
  let minor = 0;
  for (const l of lines) minor += toMinor((l.price * l.qty * (l.discountPct || 0)) / 100);
  let extra = 0;
  try {
    extra = invoiceAmount ? toMinor(invoiceAmount) : 0;
  } catch {
    extra = 0;
  }
  return minor + Math.max(0, extra);
}
