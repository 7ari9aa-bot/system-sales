/** String-safe money for the create-order dialog — no float64 anywhere.
 *
 *  §47's rule in `backend/app/modules/orders/money.py` is that money is a
 *  `Decimal` quantized to the currency's places and never a float. The client
 *  had no equivalent: the old dialog priced a cart with
 *  `Number(v.price) * line.quantity` summed in float64, and `formatMoney` in
 *  `src/lib/utils.ts` deliberately refuses to coerce a string amount back
 *  through float. This module is the missing half — every figure below is a
 *  plain decimal STRING or a `bigint` of minor units, so the total the merchant
 *  sees before submitting is the total the server will store, digit for digit.
 *
 *  Two scales, because the backend runs two:
 *  * STORAGE scale is always 2 places — `money.py:MONEY_QUANTUM` /
 *    `currency.STORED_DECIMALS`, and every MONEY column is `NUMERIC(14, 2)`.
 *    Prices arrive on this scale, and so does `grand_total`.
 *  * INPUT scale is the tenant's ISO-4217 exponent (`currency.exponent_of`),
 *    which is what a merchant is allowed to TYPE: a yen tenant gets whole yen,
 *    an egp tenant gets hundredths. `inputScale()` caps it at the storage
 *    scale, because a currency the columns cannot hold (the three-decimal Gulf
 *    dinars, which `currency.storage_refusal` already refuses as a tenant
 *    currency) must not be accepted here either — silently rounding the third
 *    place away is exactly the "guard reasoned about a value the database never
 *    stored" bug `to_money` documents.
 *
 *  No `Number()`, no `parseFloat`, no `+` on decimal strings, no eslint escapes.
 */

/** Mirror of `app/core/currency.CURRENCY_EXPONENTS` — digits after the decimal
 *  point. An unlisted code has no entry and is treated as 2, matching
 *  `money.py:_exponent_for` (`2 if exponent is None else exponent`).
 *  `currencyExponent` checks `Object.hasOwn` first, so a code like
 *  "constructor" answers 2 instead of handing back a function off the
 *  prototype chain — the one way a lookup here could ever produce a NaN. */
const CURRENCY_EXPONENTS: Record<string, number> = {
  USD: 2,
  EUR: 2,
  GBP: 2,
  SAR: 2,
  AED: 2,
  EGP: 2,
  MAD: 2,
  TND: 2,
  LBP: 2,
  SYP: 2,
  YER: 2,
  SOS: 2,
  DJF: 0,
  GNF: 0,
  JPY: 0,
  KRW: 0,
  VUV: 0,
  XOF: 0,
  XAF: 0,
  CLP: 0,
  ISK: 0,
  IQD: 3,
  BHD: 3,
  JOD: 3,
  KWD: 3,
  OMR: 3,
};

/** Places the MONEY columns hold — `currency.STORED_DECIMALS`. */
export const STORAGE_SCALE = 2;

/** `10n ** BigInt(n)` without a bigint literal, so this file stays readable. */
function pow10(n: number): bigint {
  let out = 1n;
  for (let i = 0; i < n; i += 1) out *= 10n;
  return out;
}

/** The tenant currency's ISO-4217 exponent (2 when the code is unknown). */
export function currencyExponent(code: string | null | undefined): number {
  const trimmed = code?.trim().toUpperCase();
  if (!trimmed || !Object.hasOwn(CURRENCY_EXPONENTS, trimmed)) return 2;
  return CURRENCY_EXPONENTS[trimmed];
}

/** Places a merchant may type for this tenant. */
export function inputScale(code: string | null | undefined): number {
  return Math.min(currencyExponent(code), STORAGE_SCALE);
}

/** A plain non-negative decimal: digits, at most one dot, no sign, no
 *  exponent notation, no thousands separator. This is the whole "never NaN"
 *  rule — anything that is not this shape is rejected before it can be
 *  converted, so `NaN`, `Infinity`, `-5` and `1e3` all fail here rather than
 *  reaching the server (or, worse, `Decimal("NaN")`). */
const PLAIN_DECIMAL = /^\d+(?:\.\d+)?$/;

/** `NUMERIC(14, 2)` holds 12 integer digits; beyond that Postgres errors. */
const MAX_INTEGER_DIGITS = 12;

export type MoneyParse =
  /** The field holds nothing — the merchant never touched it. */
  | { state: "empty" }
  /** The text cannot be money. `reason` is a message key, never a code. */
  | { state: "invalid"; reason: MoneyRejection }
  /** The text is money: `minor` is storage-scale cents, `amount` the same
   *  value rendered for the wire ("12.50"). */
  | { state: "ok"; minor: bigint; amount: string };

export type MoneyRejection = "not_a_number" | "too_precise" | "too_large" | "negative";

/** Minor units at the STORAGE scale (hundredths), so every amount in a sum is
 *  on one scale no matter which currency the tenant trades in. */
export function parseMoney(raw: string, scale: number): MoneyParse {
  const text = raw.trim();
  if (text === "") return { state: "empty" };
  if (text.startsWith("-") || text.startsWith("+")) {
    return { state: "invalid", reason: "negative" };
  }
  if (!PLAIN_DECIMAL.test(text)) return { state: "invalid", reason: "not_a_number" };
  const [int, frac = ""] = text.split(".");
  if (frac.length > scale) return { state: "invalid", reason: "too_precise" };
  const bare = int.replace(/^0+(?=\d)/, "");
  if (bare.length > MAX_INTEGER_DIGITS) return { state: "invalid", reason: "too_large" };
  const minor = toMinor(bare, frac, scale) * pow10(STORAGE_SCALE - scale);
  return { state: "ok", minor, amount: renderMinor(minor, STORAGE_SCALE) };
}

/** `int`/`frac` already validated: the value in minor units at `scale`. */
function toMinor(int: string, frac: string, scale: number): bigint {
  const padded = (frac + "0".repeat(scale)).slice(0, scale);
  return BigInt(int || "0") * pow10(scale) + BigInt(padded || "0");
}

/** A decimal string at `scale` places, negative sign kept. Exact: bigint in,
 *  text out — no division, no float. */
export function renderMinor(minor: bigint, scale: number): string {
  const negative = minor < 0n;
  const digits = (negative ? -minor : minor).toString();
  if (scale <= 0) return `${negative ? "-" : ""}${digits || "0"}`;
  const padded = digits.padStart(scale + 1, "0");
  return `${negative ? "-" : ""}${padded.slice(0, -scale)}.${padded.slice(-scale)}`;
}

/** A catalog price (`Variant.price`, a string like "120.00") at storage scale.
 *  `null` means the row is not a plain decimal — the estimate then says so
 *  instead of showing a number computed from nothing. */
export function priceMinor(price: string | null | undefined): bigint | null {
  const text = price?.trim() ?? "";
  if (text === "" || !PLAIN_DECIMAL.test(text)) return null;
  const [int, frac = ""] = text.split(".");
  // A price with more places than the columns hold is rounded the same way
  // `to_money` rounds it server-side: ROUND_HALF_UP at 2 places. The dropping
  // digit is compared as text, so no amount widens through a float to find out.
  if (frac.length <= STORAGE_SCALE) return toMinor(int, frac, STORAGE_SCALE);
  const kept = frac.slice(0, STORAGE_SCALE);
  const bump = frac[STORAGE_SCALE] >= "5" ? 1n : 0n;
  return toMinor(int, kept, STORAGE_SCALE) + bump;
}

/** One line: unit price × whole quantity. Integer multiplication on minor
 *  units, so 3 × 0.10 is 30 minor and never 0.30000000000000004. */
export function lineTotalMinor(
  price: string | null | undefined,
  quantity: number,
): bigint | null {
  if (!Number.isInteger(quantity) || quantity <= 0) return null;
  const unit = priceMinor(price);
  return unit === null ? null : unit * BigInt(quantity);
}

export type TotalsInput = {
  subtotal: bigint;
  discount: bigint;
  shipping: bigint;
  tax: bigint;
};

/** `grand = subtotal - discount + shipping + tax`, on minor units. */
export function grandTotalMinor({ subtotal, discount, shipping, tax }: TotalsInput): bigint {
  return subtotal - discount + shipping + tax;
}

/** The server's own refusal, mirrored so a merchant learns it while typing
 *  rather than from a 400 after the click: `compute_totals` rejects a negative
 *  grand total ("a negative total is a refund, and a refund is a money
 *  movement with a row of its own"). */
export function discountExceedsTotal(totals: TotalsInput): boolean {
  return grandTotalMinor(totals) < 0n;
}
