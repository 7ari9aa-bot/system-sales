/** The create-order request: what goes on the wire, and what it adds up to.
 *
 *  The single source of truth for the shape `POST /api/v1/orders` accepts
 *  (`backend/app/modules/orders/router.py:CreateOrderRequest`):
 *
 *      customer_id     uuid
 *      items[]         { variant_id: uuid, quantity: int > 0 }   min_length 1
 *      channel         str, default "dashboard"
 *      shipping_address dict | None
 *      discount_total  Decimal | None, ge 0     (absent = 0.00 server-side)
 *      shipping_total  Decimal | None, ge 0
 *      tax_total       Decimal | None, ge 0
 *
 *  `grand_total` is NOT a client field. The server computes it
 *  (`money.py:compute_totals`) as `subtotal - discount + shipping + tax`; this
 *  module predicts that same figure locally with the string-safe helpers in
 *  `./money.ts`, which is the only honest way to label it "total" before the
 *  write.
 *
 *  Money fields are sent ONLY when the merchant typed them. An untouched form
 *  produces `{customer_id, items, channel}` — byte-for-byte the payload this
 *  screen sent before the money inputs existed. That matters beyond tidiness:
 *  the idempotency guard hashes the raw request body, so a key replayed with a
 *  different body is a 409. Emitting `"0.00"` for fields nobody filled in would
 *  make the retry of an edited draft differ from the original send in the
 *  places that decide whether the write runs.
 */

import {
  STORAGE_SCALE,
  discountExceedsTotal,
  grandTotalMinor,
  lineTotalMinor,
  parseMoney,
  renderMinor,
  type MoneyRejection,
} from "./money";

export type OrderLine = { variant_id: string; quantity: number };

export type MoneyField = "discount" | "shipping" | "tax";

/** What the merchant has typed, verbatim. Empty string = never touched. */
export type MoneyDraft = Record<MoneyField, string>;

export const MONEY_FIELDS: readonly MoneyField[] = ["discount", "shipping", "tax"];

/** The wire payload. Amounts are STRINGS: a JSON number would already have
 *  passed through float64 before the server's `Decimal` ever saw it. */
export type CreateOrderPayload = {
  customer_id: string;
  items: { variant_id: string; quantity: number }[];
  channel: "dashboard";
  discount_total?: string;
  shipping_total?: string;
  tax_total?: string;
};

/** `router.create_order`'s response — every money figure is a Decimal string. */
export type CreateOrderResponse = {
  id: string;
  number: string;
  status: string;
  subtotal: string;
  discount_total: string;
  shipping_total: string;
  tax_total: string;
  grand_total: string;
  currency: string;
};

export type MoneyFieldState = {
  /** Storage-scale minor units; 0 when the field is empty or invalid. */
  minor: bigint;
  error: MoneyRejection | null;
  /** True when the merchant put something in the box, valid or not. */
  touched: boolean;
};

export type OrderMoneySummary = {
  fields: Record<MoneyField, MoneyFieldState>;
  subtotal: bigint;
  grand: bigint;
  /** A discount past subtotal + shipping + tax — `compute_totals` refuses it
   *  with a 400, so the dialog refuses the click. */
  negativeTotal: boolean;
  /** A chosen line's price could not be read as a plain decimal, so the
   *  subtotal is not trustworthy and the dialog must not claim it is. */
  unpriced: boolean;
  valid: boolean;
};

export function summarizeOrderMoney(input: {
  lines: OrderLine[];
  /** A chosen variant's unit price as the catalog sent it ("120.00"), or
   *  undefined when the variant is unknown. */
  priceOf: (variantId: string) => string | null | undefined;
  money: MoneyDraft;
  /** Places a merchant may type: the tenant's ISO-4217 exponent, capped at the
   *  storage scale by `inputScale()`. */
  scale: number;
}): OrderMoneySummary {
  const subtotal = input.lines.reduce((sum, line) => {
    const total = lineTotalMinor(input.priceOf(line.variant_id), line.quantity);
    return sum + (total ?? 0n);
  }, 0n);

  const fields = {} as Record<MoneyField, MoneyFieldState>;
  let anyInvalid = false;
  for (const field of MONEY_FIELDS) {
    const parsed = parseMoney(input.money[field], input.scale);
    if (parsed.state === "empty") {
      fields[field] = { minor: 0n, error: null, touched: false };
    } else if (parsed.state === "invalid") {
      fields[field] = { minor: 0n, error: parsed.reason, touched: true };
      anyInvalid = true;
    } else {
      fields[field] = { minor: parsed.minor, error: null, touched: true };
    }
  }

  const totals = {
    subtotal,
    discount: fields.discount.minor,
    shipping: fields.shipping.minor,
    tax: fields.tax.minor,
  };
  const negativeTotal = discountExceedsTotal(totals);
  const unpriced = input.lines.some(
    (line) => lineTotalMinor(input.priceOf(line.variant_id), line.quantity) === null,
  );

  return {
    fields,
    subtotal,
    grand: grandTotalMinor(totals),
    negativeTotal,
    unpriced,
    valid: !anyInvalid && !negativeTotal && !unpriced,
  };
}

/** The exact body for one submit. Money keys appear only for fields the
 *  merchant typed, rendered at the storage scale so "12.5" and "12.500" (both
 *  refused upstream, so only well-formed text arrives here) and "12.50" all put
 *  the same bytes on the wire. */
export function buildCreateOrderPayload(input: {
  customerId: string;
  lines: OrderLine[];
  summary: OrderMoneySummary;
}): CreateOrderPayload {
  const payload: CreateOrderPayload = {
    customer_id: input.customerId,
    items: input.lines.map((line) => ({
      variant_id: line.variant_id,
      quantity: line.quantity,
    })),
    channel: "dashboard",
  };
  for (const field of MONEY_FIELDS) {
    const state = input.summary.fields[field];
    if (!state.touched || state.error !== null) continue;
    const amount = renderMinor(state.minor, STORAGE_SCALE);
    if (field === "discount") payload.discount_total = amount;
    else if (field === "shipping") payload.shipping_total = amount;
    else payload.tax_total = amount;
  }
  return payload;
}
