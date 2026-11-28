/**
 * Money for the cashier. One discipline, mirrors the backend (orders/money.py):
 *
 *  - Amounts live as INTEGER MINOR UNITS (cents). Never a float in arithmetic.
 *  - Rounding is ROUND_HALF_UP to 2 places, done on the DECIMAL TEXT, because
 *    the float 1.005 is really 1.00499999999999989... and would round the wrong way.
 *  - On the wire, money is a string matching ^\d+(\.\d{1,2})?$ (pos/router.py _MONEY):
 *    non-negative, at most 2 decimals. Direction (in/out, sale/refund) is a
 *    separate field, never a minus sign.
 *
 * Every function either returns a valid value or THROWS. Nothing returns NaN.
 */

const WIRE_RE = /^\d+(\.\d{1,2})?$/;

/** True only for exactly what the backend accepts. */
export function isWireMoney(value) {
  return typeof value === "string" && WIRE_RE.test(value);
}

/** Number -> plain decimal text without exponent, using the shortest round-trip form. */
function numberToDecimalText(n) {
  if (!Number.isFinite(n)) throw new TypeError(`money: not a finite number (${n})`);
  const s = String(n);
  if (!/e/i.test(s)) return s;
  // 1e-7 / 1.5e21: expand without losing digits.
  const [mant, expRaw] = s.toLowerCase().split("e");
  const exp = Number(expRaw);
  const neg = mant.startsWith("-");
  const [intPart, fracPart = ""] = mant.replace("-", "").split(".");
  const digits = intPart + fracPart;
  const pointPos = intPart.length + exp;
  let out;
  if (pointPos <= 0) out = `0.${"0".repeat(-pointPos)}${digits}`;
  else if (pointPos >= digits.length) out = digits + "0".repeat(pointPos - digits.length);
  else out = `${digits.slice(0, pointPos)}.${digits.slice(pointPos)}`;
  return (neg ? "-" : "") + out;
}

/**
 * Decimal text -> integer cents, ROUND_HALF_UP (away from zero on exact .5).
 * Accepts numbers and strings (with any number of decimals); throws otherwise.
 */
export function toMinor(value) {
  let text;
  if (typeof value === "number") text = numberToDecimalText(value);
  else if (typeof value === "string") text = value.trim();
  else throw new TypeError(`money: expected number or string, got ${value === null ? "null" : typeof value}`);

  const m = /^([+-])?(\d+)(?:\.(\d+))?$/.exec(text);
  if (!m) throw new TypeError(`money: not a decimal amount ("${text}")`);
  const negative = m[1] === "-";
  const whole = m[2];
  const frac = m[3] ?? "";

  const cents = BigInt(whole) * 100n + BigInt((frac + "00").slice(0, 2));
  const roundUp = frac.length > 2 && frac.charCodeAt(2) >= 53; // third decimal digit >= 5
  const total = cents + (roundUp ? 1n : 0n);
  const result = Number(negative ? -total : total);
  if (!Number.isSafeInteger(result)) throw new RangeError("money: amount too large");
  return result === 0 ? 0 : result; // never -0
}

/** Integer cents -> "12.34" (negative allowed for internal results like change owed). */
export function fromMinor(minor) {
  if (!Number.isSafeInteger(minor)) throw new TypeError(`money: minor units must be a safe integer (${minor})`);
  const neg = minor < 0;
  const abs = Math.abs(minor);
  const s = `${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
  return neg ? `-${s}` : s;
}

/** Anything -> backend-valid wire string. Throws on negatives. */
export function toWire(value) {
  const minor = toMinor(value);
  if (minor < 0) throw new RangeError("money: negative amount cannot go on the wire");
  return fromMinor(minor);
}

/** Parse for display/inspection. */
export function parseMoney(value) {
  const minor = toMinor(value);
  return { minor, text: fromMinor(minor) };
}

export function addMoney(a, b) {
  return fromMinor(toMinor(a) + toMinor(b));
}

export function subMoney(a, b) {
  return fromMinor(toMinor(a) - toMinor(b));
}

export function sumMoney(values) {
  let total = 0;
  for (const v of values) total += toMinor(v);
  return fromMinor(total);
}

/** unit price x integer quantity, rounded once on the line total. */
export function mulMoney(unit, quantity) {
  if (!Number.isInteger(quantity) || quantity < 0) throw new RangeError("money: quantity must be a non-negative integer");
  return fromMinor(toMinor(unit) * quantity);
}

/**
 * Split a total into n parts that always sum to the total.
 * Leftover cents go to the first parts: 100.00 / 3 -> 33.34, 33.33, 33.33.
 */
export function splitEvenly(total, n) {
  if (!Number.isInteger(n) || n < 1) throw new RangeError("money: split count must be >= 1");
  const minor = toMinor(total);
  if (minor < 0) throw new RangeError("money: cannot split a negative amount");
  const base = Math.floor(minor / n);
  const extra = minor - base * n;
  return Array.from({ length: n }, (_, i) => fromMinor(base + (i < extra ? 1 : 0)));
}
