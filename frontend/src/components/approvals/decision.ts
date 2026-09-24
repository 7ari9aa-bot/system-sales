/** The approval decision's request: what goes on the wire, and what a refusal means.
 *
 *  Built the same way as `../orders/order-ops.ts` on purpose: no React, no `@/`
 *  imports, no network. Every rule the server enforces on the decide route is
 *  decided here as a pure function, so a dialog can refuse a click before it
 *  spends a key, and so the rule is testable in a node worker without a browser
 *  (`e2e/approvals.spec.ts` runs these). `classifyWriteError` is reused from
 *  `order-ops` because it carries no order-domain text — that is the shared piece,
 *  not the money copy the approval screen has no use for.
 *
 *  The contract is `backend/app/modules/ai/router.py`, transcribed:
 *
 *      GET  /ai/approvals?status=            -> { items: [_approval_out], truncated: bool }
 *                                                                  (router.py:309-317)
 *      POST /ai/approvals/{id}/decide {decision, reason | None} -> { ..._approval_out, resumed }
 *                                                                        (router.py:320-359)
 *
 *  `decision` is a CLOSED vocabulary — `ApprovalDecisionRequest.decision`, and
 *  `ApprovalService.decide` refuses anything else (router.py:285, approvals.py:111).
 *  A human reviewer here grants or kills a parked action, so the screen offers
 *  APPROVE (`"APPROVED"`) and DENY (`"REJECTED"`); `"CANCELLED"` is the third legal
 *  word but it is the agent's own withdrawal, not a reviewer's decision, so it is
 *  deliberately not offered.
 *
 *  The reason field is `reason`, NOT `rejection_reason` (router.py:286). The
 *  earlier screen sent `rejection_reason` and the server silently dropped it, so a
 *  deny that looked annotated stored nothing.
 */

import { classifyWriteError, isTerminalRefusal, type WriteRefusal } from "../orders/order-ops";

/* ---------------------------------------------------------- the vocabulary */

/** `ApprovalService.decide`'s two reviewer words. A parked action is decided
 *  with one of these and nothing else (approvals.py:102,111). */
export const APPROVE = "APPROVED";
export const DENY = "REJECTED";
export type Decision = typeof APPROVE | typeof DENY;

/** Only a `PENDING` approval can be decided; the service raises on any other
 *  status (approvals.py:131), so the buttons are offered only on this one —
 *  courtesy, the service is the authority. */
export const PENDING = "PENDING";

export function isDecidable(status: string | null | undefined): boolean {
  return status === PENDING;
}

/** `ApprovalDecisionRequest.reason` is `max_length=512` (router.py:286). The
 *  `rejection_reason` COLUMN is unbounded `Text` (models.py:342), so a longer
 *  reason is refused by the request model (a 422) before it can reach the
 *  database: the cap that matters is the model's, enforced here. */
export const DECISION_REASON_MAX = 512;

/** `approvals.py::APPROVALS_PAGE_SIZE` — how many rows one read of the queue
 *  returns. The list is bounded and the route answers `truncated: true` when it
 *  cut rows off, so a full page is never evidence of an empty queue: the screen
 *  says so instead of letting a reviewer decide they have seen everything. */
export const APPROVALS_PAGE_SIZE = 100;

/* --------------------------------------------------------- the wire payload */

/** `ApprovalDecisionRequest`, field-for-field. `reason` is optional, so a blank
 *  one is ABSENT — an empty string would store a reason that says nothing. */
export type DecisionPayload = { decision: Decision; reason?: string };

export type DecisionError = "unknown_decision" | "reason_too_long";

export type DecisionDraft = { decision: Decision; reason: string };

/** Validate a decision before it spends a key.
 *
 *  A reason is only ever sent on a DENY: `decide` writes whatever reason arrives
 *  into `rejection_reason` regardless of the decision (approvals.py:142), so an
 *  "approve with a reason" would land a rejection note on a granted action. The
 *  server does NOT require a reason on deny (`reason` defaults to `None`), so a
 *  blank one is sent as absent rather than invented — the previous screen's
 *  hardcoded "rejected by human reviewer" was the screen putting words in the
 *  reviewer's mouth. */
export function buildDecisionPayload(
  draft: DecisionDraft,
): { ok: true; body: DecisionPayload } | { ok: false; error: DecisionError } {
  if (draft.decision !== APPROVE && draft.decision !== DENY) {
    return { ok: false, error: "unknown_decision" };
  }
  const reason = draft.reason.trim();
  if (reason.length > DECISION_REASON_MAX) return { ok: false, error: "reason_too_long" };

  const body: DecisionPayload = { decision: draft.decision };
  if (draft.decision === DENY && reason !== "") body.reason = reason;
  return { ok: true, body };
}

/* ------------------------------------------------------ the argument snapshot */

/** One rendered line of the argument snapshot. `value` is already TEXT: the
 *  decision is made against what the screen can read, not a re-typed number. */
export type ArgumentEntry = { key: string; value: string };

/** A single payload value as text, never through `Number()` or `.toFixed()`.
 *  §47's rule is that money crosses JSON as `str(Decimal)`, so a money argument
 *  arrives here already a string ("250.00") and this returns it untouched; a
 *  nested object is shown as compact JSON so the reviewer sees the whole argument
 *  the approval is bound to. Nothing here widens a figure through float64. */
export function renderArgumentValue(value: unknown): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** The arguments this decision actually binds to.
 *
 *  The gate parks a call with `payload = {"arguments": kwargs}` (runtime.py:687),
 *  and `decide` is bound to that snapshot through `payload_hash` (G-02) — so what
 *  a reviewer must read is the inner `arguments` object, and only falls back to
 *  the whole payload when a row was created without the wrapper. Rendered as text
 *  so a person can decide "without opening a database." */
export function argumentEntries(
  payload: Record<string, unknown> | null | undefined,
): ArgumentEntry[] {
  if (!payload || typeof payload !== "object") return [];
  const args = payload.arguments;
  const source =
    args && typeof args === "object" && !Array.isArray(args)
      ? (args as Record<string, unknown>)
      : payload;
  return Object.entries(source).map(([key, value]) => ({
    key,
    value: renderArgumentValue(value),
  }));
}

/* ------------------------------------------------------------------ refusals */

/** The decision-specific classes, layered on the shared write-refusal shape.
 *  `terminal` is the dialog's "keep the key, stop submitting, re-read the
 *  queue" signal — wider than the generic 409/412 terminal set, because of how
 *  this route answers a decision it can no longer take. */
export type DecisionRefusal = WriteRefusal & { terminal: boolean };

/** The server's own sentences for "this approval can no longer be decided."
 *
 *  `ApprovalService.decide` raises `ValidationError` — which maps to HTTP **400**
 *  (`app/core/errors.py:65-68`), NOT 409 — for an already-decided approval
 *  ("approval already APPROVED", approvals.py:132) and an expired one
 *  ("approval request expired", approvals.py:138), and `NotFoundError` (404) when
 *  the row is gone (approvals.py:130). The generic `classifyWriteError` calls a
 *  400/404 `refused` and therefore resendable; for a decision that is wrong — the
 *  approval has left PENDING, so re-sending cannot help and, worse, minting a
 *  fresh key and re-firing an APPROVE is exactly the double-grant this screen
 *  exists to prevent. `/api/v1/ai/approvals` is not on the idempotency allow-list
 *  (`app/core/idempotency.py:115-123`), so nothing dedupes it server-side but the
 *  `status != PENDING` gate — the very sentence matched here. */
const DECIDED_SENTENCE = /already|expired|not found/i;

export function classifyDecisionError(err: unknown): DecisionRefusal {
  const base = classifyWriteError(err);
  const terminal =
    isTerminalRefusal(base) || (base.kind === "refused" && DECIDED_SENTENCE.test(base.message));
  return { ...base, terminal };
}
