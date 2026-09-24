/** The order operations' requests: what goes on the wire, and what a refusal means.
 *
 *  Sibling of `./order-request.ts` (the create path) and built the same way on
 *  purpose: no React, no network, no `@/` imports. Every rule the server enforces
 *  on these routes is decided here as a pure function, so a dialog can refuse a
 *  click before it spends an Idempotency-Key, and so the rule is testable in a
 *  node worker without a browser (`e2e/order-ops.spec.ts` runs these).
 *
 *  The contract is `backend/app/modules/orders/router.py`, transcribed:
 *
 *      POST  /orders/{id}/payments/{pid}/refunds   {amount: Decimal gt 0, reason ≤ 512}  -> 201
 *      POST  /orders/{id}/status                   {status, note | None}                 -> {ok}
 *      POST  /orders/{id}/return                   {reason ∈ RETURN_REASONS}             -> {saga_*}
 *      PATCH /orders/{id}/shipping                 If-Match, {shipping_address?, shipping_method ≤ 31}
 *
 *  Money is a STRING in every payload below. `parseMoney`/`renderMinor` in
 *  `./money.ts` are the only path from a typed figure to a number, and they run
 *  on `bigint` minor units — a JSON number would have crossed float64 before the
 *  server's `Decimal` saw it (§47/ADR-053).
 *
 *  `classifyWriteError` is the "refused, and why" half of the surface. It keeps
 *  the STATUS, because the actions a 409 and a 400 demand are opposites: a 400
 *  says the draft is wrong and may be fixed and resent under the same key, a 409
 *  says the attempt is over and resending it — especially under a freshly minted
 *  key — risks giving the money back twice. `src/lib/api.ts:isConflictError`
 *  spells the same rule out; this file exists so the dialogs can state it without
 *  importing the client (and so a node worker can test it).
 */

import { parseMoney, priceMinor, type MoneyRejection } from "./money";

/* ------------------------------------------------------------------ limits */

/** `RefundCreateRequest.reason` — `max_length=512`, and it is the column width. */
export const REFUND_REASON_MAX = 512;
/** `order_status_history.note` is `String(512)` while `StatusChangeRequest.note`
 *  declares no maximum: a longer note is a database error, not a 400, so the cap
 *  has to be enforced HERE (`orders/models.py:OrderStatusHistory`). */
export const CANCEL_NOTE_MAX = 512;
/** `ShippingUpdateRequest.shipping_method` — `max_length=31`. */
export const SHIPPING_METHOD_MAX = 31;

/** `returns.RETURN_REASONS` — a CLOSED vocabulary. Anything else is a
 *  `ValidationError("unknown return reason: …")` (400) server-side, so the
 *  dialog offers these two and nothing else; free text is not an option here. */
export const RETURN_REASONS = ["customer_return", "delivery_failed"] as const;
export type ReturnReason = (typeof RETURN_REASONS)[number];
/** `ReturnRequest.reason`'s own default, and the value the dialog opens on. */
export const DEFAULT_RETURN_REASON: ReturnReason = "customer_return";

/* --------------------------------------------------------- what can happen */

/** `service.TRANSITIONS` edges INTO `cancelled`: pending, confirmed, processing.
 *  Deliberately wider than `_CANCELLABLE_STATUSES` ({pending, confirmed}), which
 *  is the narrower rule `POST /orders/{id}/cancel` applies. This surface cancels
 *  through `/status` (only that route carries a reason), so the state machine it
 *  must match is `TRANSITIONS` — and `change_status` is the authority either way. */
export const CANCELLABLE_STATUSES: readonly string[] = ["pending", "confirmed", "processing"];

/** `service._SHIPPING_EDITABLE_STATUSES`. After `shipped` the address on the row
 *  is history, and the next leg is a shipment record, not a correction. */
export const SHIPPING_EDITABLE_STATUSES: readonly string[] = ["pending", "confirmed", "processing"];

/** `returns.RETURNABLE_STATUSES` — the parcel has left. */
export const RETURNABLE_STATUSES: readonly string[] = ["shipped", "delivered"];

/** `service.register_refund` accepts a refund against these and nothing else:
 *  refunding a pending or failed intent would invent money never taken. */
export const REFUNDABLE_PAYMENT_STATUSES: readonly string[] = ["captured", "partially_refunded"];

export function canCancel(status: string | null | undefined): boolean {
  return CANCELLABLE_STATUSES.includes(status ?? "");
}

export function canEditShipping(status: string | null | undefined): boolean {
  return SHIPPING_EDITABLE_STATUSES.includes(status ?? "");
}

export function canReturn(status: string | null | undefined): boolean {
  return RETURNABLE_STATUSES.includes(status ?? "");
}

export function isRefundablePayment(status: string | null | undefined): boolean {
  return REFUNDABLE_PAYMENT_STATUSES.includes(status ?? "");
}

/* ------------------------------------------------------------------- refund */

/** `RefundCreateRequest`. `reason` is optional, so a blank one is ABSENT here —
 *  an empty string would be stored as a note that says nothing. */
export type RefundPayload = { amount: string; reason?: string };

export type RefundDraft = { amount: string; reason: string };

/** Why the dialog refuses the click before it sends anything. `MoneyRejection`
 *  names what is wrong with the number; the rest are this route's own rules. */
export type RefundError =
  | "empty"
  | "zero"
  | "over_captured"
  | "reason_too_long"
  | MoneyRejection;

/** The most this payment can give back, in minor units, or `null` when the read
 *  does not make it computable.
 *
 *  `GET /orders/{id}/payments` carries the payment's `amount` and its `status`,
 *  but NOT the refunds already registered against it (those live in a table the
 *  route does not read), so a `partially_refunded` capture has an unknown
 *  remainder. Inventing one — `amount − 0` — would let the dialog block a legal
 *  refund or wave through a too-large one. So the cap is claimed only on a clean
 *  capture, and everywhere else the server's 409 is the authority and the screen
 *  shows its sentence verbatim. */
export function refundCapMinor(payment: {
  status: string | null | undefined;
  amount: string | null | undefined;
}): bigint | null {
  if (payment.status !== "captured") return null;
  return priceMinor(payment.amount);
}

/** Validate a refund draft against the route's own rules.
 *  `scale` is the tenant's input scale (`inputScale(currency)`), so a yen tenant
 *  is not told a fraction is fine and an EGP tenant is not told 1.234 is. */
export function buildRefundPayload(
  draft: RefundDraft,
  options: { scale: number; capMinor: bigint | null },
): { ok: true; body: RefundPayload } | { ok: false; error: RefundError } {
  const reason = draft.reason.trim();
  if (reason.length > REFUND_REASON_MAX) return { ok: false, error: "reason_too_long" };

  const parsed = parseMoney(draft.amount, options.scale);
  if (parsed.state === "empty") return { ok: false, error: "empty" };
  if (parsed.state === "invalid") return { ok: false, error: parsed.reason };
  // `positive_money` / `Field(gt=0)` refuse zero, so this is a refusal and not a
  // no-op: a 0.00 refund would write a ledger row that moves nothing.
  if (parsed.minor <= 0n) return { ok: false, error: "zero" };
  if (options.capMinor !== null && parsed.minor > options.capMinor) {
    return { ok: false, error: "over_captured" };
  }

  const body: RefundPayload = { amount: parsed.amount };
  if (reason !== "") body.reason = reason;
  return { ok: true, body };
}

/* -------------------------------------------------------------- status/return */

/** `StatusChangeRequest` — and the reason a cancel takes.
 *
 *  `POST /orders/{id}/cancel` declares NO body, so a reason sent to it is
 *  silently dropped by FastAPI: the screen would promise a recorded reason and
 *  store nothing. `change_status` runs the same `_transition` path (stock release
 *  included) and its `note` lands in `order_status_history`, so the cancel posts
 *  THERE. An untouched note is absent, not `""`. */
export type StatusChangePayload = { status: string; note?: string };

export function buildCancelBody(note: string): StatusChangePayload {
  const trimmed = note.trim();
  const body: StatusChangePayload = { status: "cancelled" };
  if (trimmed !== "" && trimmed.length <= CANCEL_NOTE_MAX) body.note = trimmed;
  return body;
}

/** `ReturnRequest` — the reason is one of the two the saga knows. */
export type ReturnPayload = { reason: string };

export function buildReturnBody(reason: ReturnReason): ReturnPayload {
  return { reason };
}

/* ------------------------------------------------------------------ shipping */

/** `ShippingUpdateRequest`. Either field may be absent; both absent is a 400
 *  (`update_shipping` raises "nothing to change"), so this module refuses the
 *  click instead of sending it. */
export type ShippingPatch = {
  shipping_address?: Record<string, unknown>;
  shipping_method?: string;
};

export type ShippingError = "nothing_to_change" | "invalid_json" | "not_an_object" | "method_too_long";

export type ShippingDraft = { method: string; address: string };

/** The address the merchant edited, parsed as the WHOLE object it is:
 *  `update_shipping` REPLACES `shipping_address` rather than merging into it, so
 *  a partial send would delete the parts the form never showed. */
export function parseAddressJson(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: "empty" | "invalid_json" | "not_an_object" } {
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, error: "empty" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return { ok: false, error: "invalid_json" };
  }
  // `JSON.parse("null")` succeeds, and `[1,2]` is an object to `typeof` — neither
  // is an address, and `shipping_address` is a dict column.
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: "not_an_object" };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

/** Only the fields touched go out, for the same reason the create dialog sends
 *  only typed money: the body decides what the row becomes. */
export function buildShippingPayload(draft: ShippingDraft): {
  body: ShippingPatch;
  error: ShippingError | null;
} {
  const method = draft.method.trim();
  if (method.length > SHIPPING_METHOD_MAX) return { body: {}, error: "method_too_long" };

  const body: ShippingPatch = {};
  if (method !== "") body.shipping_method = method;

  const text = draft.address.trim();
  if (text !== "") {
    const parsed = parseAddressJson(text);
    if (!parsed.ok) {
      return { body: {}, error: parsed.error === "empty" ? "nothing_to_change" : parsed.error };
    }
    body.shipping_address = parsed.value;
  }

  if (body.shipping_method === undefined && body.shipping_address === undefined) {
    return { body: {}, error: "nothing_to_change" };
  }
  return { body, error: null };
}

/* ------------------------------------------------------------------ refusals */

/** The classes a write failure falls into, each answered differently by the UI:
 *
 *  * `permission` — 403. Nothing ran, so the dialog stays open and retryable;
 *    the screen's job is to show WHICH permission was missing.
 *  * `conflict`   — 409. The attempt is over: either the key was already spent or
 *    the write itself conflicted. NEVER re-mint and resend.
 *  * `stale`      — 412. The conditional write lost: re-read, do not force.
 *  * `refused`    — 4xx that is fixable (400/404/422): same key, corrected body.
 *  * `server`     — 5xx. The guard records it terminal, so the next same-key
 *    attempt is a 409; keeping the key is still the client's half of the rule.
 *  * `network`    — no status at all: the request may never have arrived.
 */
export type WriteRefusalKind = "permission" | "conflict" | "stale" | "refused" | "server" | "network";

export type WriteRefusal = { kind: WriteRefusalKind; message: string };

/** True when a refusal ends the attempt: the key must NOT be re-minted. */
export function isTerminalRefusal(refusal: WriteRefusal): boolean {
  return refusal.kind === "conflict" || refusal.kind === "stale";
}

/** Read the status off the error instead of `instanceof`-ing the client's class,
 *  so this module keeps the dependency-free shape its siblings have (and so a
 *  node worker can run it without loading the API client). */
export function classifyWriteError(err: unknown): WriteRefusal {
  const message = err instanceof Error ? err.message : err === null || err === undefined ? "" : String(err);
  const status = (err as { status?: unknown } | null)?.status;
  const code = (err as { code?: unknown } | null)?.code;
  if (typeof status !== "number") return { kind: "network", message };
  if (code === "permission_denied") return { kind: "permission", message };
  if (status === 409) return { kind: "conflict", message };
  if (status === 412) return { kind: "stale", message };
  if (status === 403 || status === 401) return { kind: "permission", message };
  if (status >= 500) return { kind: "server", message };
  return { kind: "refused", message };
}
