import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang, serverError } from "./support";
import { ApiError } from "../src/lib/api";
import {
  argumentEntries,
  buildDecisionPayload,
  classifyDecisionError,
  isDecidable,
} from "../src/components/approvals/decision";

/* Approvals — the §135 human decision queue.
 *
 * CI-ONLY PROOF for the browser half. This sandbox cannot bind a TCP port, so no
 * browser ran the tests below; they are the same shape as `order-ops.spec.ts`,
 * whose pure cases DO run in Playwright's node worker. What is verified locally
 * is the pure module (`decision.ts`): the payload rules and the terminal-refusal
 * classification. The rest needs a runner.
 *
 * Every mocked response is transcribed from
 * `backend/app/modules/ai/router.py` — field names, shapes and codes included,
 * because a spec that mocks a shape the server does not answer proves nothing:
 *
 *   GET  /ai/approvals?status=            -> { items: [_approval_out], truncated }
 *                                                               (router.py:309-317)
 *   POST /ai/approvals/{id}/decide {decision, reason | None}
 *                                        -> { ..._approval_out, resumed }  (router.py:320-359)
 *
 * `_approval_out` fields (router.py:289-306), verbatim:
 *   id, status, action, risk_level, entity_type, entity_id, conversation_id,
 *   run_id, payload, requested_by, expires_at, decided_at, consumed_at,
 *   rejection_reason, created_at
 *
 * The decide BODY reads `reason` (router.py:286) — NOT `rejection_reason`; the
 * old client sent the wrong name and the server dropped it. `decision` is
 * `APPROVED | REJECTED | CANCELLED` (router.py:285); a human reviewer only uses
 * the first two, and both ride the SAME route (there is no separate deny endpoint).
 *
 * Terminal semantics the spec pins: `ApprovalService.decide` answers an
 * already-decided or expired approval with `ValidationError` = HTTP **400**
 * (approvals.py:131-138, errors.py:65-68), and a missing row with `NotFoundError`
 * = 404 — NOT 409. And `/api/v1/ai/approvals` is NOT on the idempotency
 * allow-list (idempotency.py:115-123), so the server never replay-dedupes this
 * route; the guard against granting the same action twice is the `status !=
 * PENDING` check, i.e. the 400 "approval already …" sentence this screen treats
 * as terminal (spend the key, stop, re-read). `requested_by` is the fixed token
 * `ai | automation | system` (models.py:316-318), so the row is asked FOR by the
 * agent, not by a named user. */

/* ------------------------------------------------------------------ fixtures */

/** `router._approval_out`, one pending HIGH-risk action. `payload.arguments.amount`
 *  is a Decimal STRING (§47) — the screen must render "250.00", never "250". */
const PENDING_APPROVAL = {
  id: "ap-1",
  status: "PENDING",
  action: "issue_refund",
  risk_level: "HIGH",
  entity_type: "order",
  entity_id: "o1",
  conversation_id: "conv-1",
  run_id: "run-1",
  payload: { arguments: { order_id: "o1", amount: "250.00", reason: "damaged on arrival" } },
  requested_by: "ai",
  expires_at: "2026-09-21T10:00:00Z",
  decided_at: null,
  consumed_at: null,
  rejection_reason: null,
  created_at: "2026-09-20T09:30:00Z",
};

/** A parked LOW-risk call with no wrapper — exercises the payload fallback and
 *  the "no arguments" branch. */
const PENDING_NO_ARGS = {
  ...PENDING_APPROVAL,
  id: "ap-2",
  action: "resend_invoice",
  risk_level: "LOW",
  payload: {},
  requested_by: "automation",
};

/** `_approval_out` after a decision, plus `resumed` (router.py:359). */
function decided(status: string, extra: Record<string, unknown> = {}) {
  return { ...PENDING_APPROVAL, status, decided_at: "2026-09-20T09:45:00Z", ...extra };
}

/** `require_permission("settings:write")` → 403 (router.py:324, errors.py:84-87). */
const FORBIDDEN = {
  error: { code: "permission_denied", message: "missing permission: settings:write", retryable: false },
};
/** `ApprovalService.decide` on a non-PENDING row → ValidationError → 400. */
const ALREADY_DECIDED = {
  error: { code: "validation_error", message: "approval already APPROVED", retryable: false },
};
/** An expired row: the service flips it to EXPIRED then raises 400 (approvals.py:134-138). */
const EXPIRED = {
  error: { code: "validation_error", message: "approval request expired", retryable: false },
};
/** A row that is gone → NotFoundError → 404. */
const NOT_FOUND = {
  error: { code: "not_found", message: "approval request not found", retryable: false },
};

/* ------------------------------------------------------------------- routing */

type DecideAnswer = "ok" | "already" | "expired" | "gone" | "forbidden" | ((attempt: number) => "ok" | "forbidden");
type ListAnswer = unknown[] | ((status: string) => unknown[]);

type Sent = { method: string; path: string; body: string; key: string | null; status: string | null };

/** Mock both approvals routes. The list is stateful so a decided row leaves the
 *  PENDING queue on the invalidation refetch — which is what makes the "the
 *  pending list empties after a decision" assertion mean something. */
async function mockApprovalsApi(
  page: Page,
  opts: { list?: ListAnswer; decide?: DecideAnswer; truncated?: boolean } = {},
): Promise<Sent[]> {
  const sent: Sent[] = [];
  let pending =
    typeof opts.list === "function" ? [] : opts.list ? [...opts.list] : [{ ...PENDING_APPROVAL }];
  let attempts = 0;

  await page.route("**/api/v1/ai/approvals**", (route: Route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const path = url.pathname;
    const status = url.searchParams.get("status");

    if (method === "GET" && path === "/api/v1/ai/approvals") {
      const items =
        typeof opts.list === "function" ? opts.list(status ?? "PENDING") : status === "PENDING" ? pending : [];
      return json(route, { items, truncated: opts.truncated ?? false });
    }

    if (method === "POST" && path.endsWith("/decide")) {
      const entry: Sent = {
        method,
        path,
        body: request.postData() ?? "",
        key: request.headers()["idempotency-key"] ?? null,
        status,
      };
      sent.push(entry);
      attempts += 1;
      const answer = opts.decide ?? "ok";
      const outcome = typeof answer === "function" ? answer(attempts) : answer;
      if (outcome === "already") return json(route, ALREADY_DECIDED, 400);
      if (outcome === "expired") return json(route, EXPIRED, 400);
      if (outcome === "gone") return json(route, NOT_FOUND, 404);
      if (outcome === "forbidden") return json(route, FORBIDDEN, 403);
      // ok: the row leaves PENDING and is returned as APPROVED, resumed.
      // `/api/v1/ai/approvals/{id}/decide` split on "/" is
      // ["", "api", "v1", "ai", "approvals", "{id}", "decide"] — the id is
      // index 5. Index 4 is the literal "approvals", which matched no row, so
      // the filter below dropped nothing and the refetched PENDING queue still
      // held the approval this dialog had just granted.
      const id = path.split("/")[5];
      const approved = id === "ap-2" ? { ...PENDING_NO_ARGS, status: "APPROVED" } : decided("APPROVED");
      pending = pending.filter((a) => (a as { id: string }).id !== id);
      return json(route, { ...approved, consumed_at: null, resumed: true }, 200);
    }
    return json(route, { items: [], truncated: false });
  });

  return sent;
}

async function gotoApprovals(page: Page) {
  await page.goto("/approvals");
}

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await seedLang(page, "en");
});

/* ------------------------------------------- the pure module (node worker) -- */

test("the decide body uses the server's `reason` field, and only on a deny with text", () => {
  // An approve never carries a reason: `decide` writes any reason into
  // `rejection_reason` regardless of the decision (approvals.py:142), so an
  // "approve with a note" would file a rejection note on a granted action.
  const approve = buildDecisionPayload({ decision: "APPROVED", reason: "  " });
  expect(approve.ok).toBe(true);
  if (approve.ok) expect(JSON.stringify(approve.body)).toBe('{"decision":"APPROVED"}');

  const deny = buildDecisionPayload({ decision: "REJECTED", reason: "wrong item" });
  expect(deny.ok).toBe(true);
  if (deny.ok) expect(JSON.stringify(deny.body)).toBe('{"decision":"REJECTED","reason":"wrong item"}');

  // A blank deny sends no reason at all — `reason` is optional server-side, and
  // an empty string would store a reason that says nothing.
  const denyBlank = buildDecisionPayload({ decision: "REJECTED", reason: "   " });
  expect(denyBlank.ok && JSON.stringify(denyBlank.body)).toBe('{"decision":"REJECTED"}');
});

test("a reason is capped at the request model's own 512", () => {
  const built = buildDecisionPayload({ decision: "REJECTED", reason: "x".repeat(513) });
  expect(built.ok).toBe(false);
  if (!built.ok) expect(built.error).toBe("reason_too_long");
  expect(buildDecisionPayload({ decision: "REJECTED", reason: "x".repeat(512) }).ok).toBe(true);
});

test("only a PENDING approval can be decided", () => {
  expect(isDecidable("PENDING")).toBe(true);
  for (const status of ["APPROVED", "REJECTED", "EXPIRED", "CANCELLED", "", null, undefined]) {
    expect(isDecidable(status as string | null), String(status)).toBe(false);
  }
});

test("the argument snapshot renders money as text — never widened through float", () => {
  const entries = argumentEntries({ arguments: { amount: "250.00", quantity: 2, note: null } });
  expect(entries).toEqual([
    { key: "amount", value: "250.00" },
    { key: "quantity", value: "2" },
    { key: "note", value: "—" },
  ]);
  // The §47 point: a Decimal string survives exactly; a float round-trip would
  // have dropped the trailing zero.
  const amount = entries.find((e) => e.key === "amount");
  expect(amount?.value).toBe("250.00");
  // No `arguments` wrapper → fall back to the payload itself; empty → nothing.
  expect(argumentEntries({ direct: "value" })).toEqual([{ key: "direct", value: "value" }]);
  expect(argumentEntries({})).toEqual([]);
  expect(argumentEntries(null)).toEqual([]);
});

test("an already-decided or expired approval is terminal; a 403 is not", () => {
  // The server answers these with 400/404 (not 409) — the generic classifier
  // would call a 400 resendable; for a decision they mean "stop, re-read."
  expect(
    classifyDecisionError(new ApiError("approval already APPROVED", { status: 400, code: "validation_error" })),
  ).toMatchObject({ kind: "refused", terminal: true });
  expect(
    classifyDecisionError(new ApiError("approval request expired", { status: 400, code: "validation_error" })).terminal,
  ).toBe(true);
  expect(
    classifyDecisionError(new ApiError("approval request not found", { status: 404, code: "not_found" })).terminal,
  ).toBe(true);

  // A 403 ran nothing: retryable, key kept, so NOT terminal.
  const forbidden = classifyDecisionError(
    new ApiError("missing permission: settings:write", { status: 403, code: "permission_denied" }),
  );
  expect(forbidden).toMatchObject({ kind: "permission", terminal: false });

  // A real idempotency 409 is terminal via the shared rule.
  expect(
    classifyDecisionError(new ApiError("Idempotency-Key reused", { status: 409, code: "conflict" })).terminal,
  ).toBe(true);
  // A fixable 400 that is NOT a decided/expired sentence stays resendable.
  expect(
    classifyDecisionError(new ApiError("invalid decision: MAYBE", { status: 400, code: "validation_error" })),
  ).toMatchObject({ kind: "refused", terminal: false });
  // No status at all is a transport failure, not a refusal.
  expect(classifyDecisionError(new Error("Failed to fetch"))).toMatchObject({ kind: "network", terminal: false });
});

/* --------------------------------------------------------- the pending list */

test("the pending queue shows what, who, when, and the bound arguments as text", async ({ page }) => {
  await mockApprovalsApi(page);
  await gotoApprovals(page);

  await expect(page.getByTestId("approval-ap-1")).toBeVisible();
  // What is being approved (the action token, LTR) + risk + status.
  await expect(page.getByTestId("approval-ap-1")).toContainText("issue_refund");
  await expect(page.getByTestId("approval-ap-1")).toContainText("High");
  await expect(page.getByTestId("approval-ap-1")).toContainText("Awaiting approval");
  // Who asked — the fixed `ai` token, and the argument snapshot rendered as text.
  await expect(page.getByTestId("approval-ap-1")).toContainText("Requested by");
  await expect(page.getByTestId("approval-args-ap-1")).toContainText("amount");
  // §47 in the browser: the Decimal string survives, trailing zero and all.
  await expect(page.getByTestId("approval-args-ap-1")).toContainText("250.00");
  await expect(page.getByTestId("approval-args-ap-1")).not.toContainText("250.000");
  // A PENDING row offers the two decisions.
  await expect(page.getByTestId("approve-ap-1")).toBeEnabled();
  await expect(page.getByTestId("deny-ap-1")).toBeEnabled();
});

test("no-argument and empty queues read honestly, never as a phantom row", async ({ page }) => {
  await mockApprovalsApi(page, { list: [{ ...PENDING_NO_ARGS, payload: {} }] });
  await gotoApprovals(page);
  await expect(page.getByTestId("approval-ap-2")).toContainText("No arguments recorded for this action");

  await mockApprovalsApi(page, { list: [] });
  await gotoApprovals(page);
  await expect(page.getByTestId("approvals-empty")).toBeVisible();
  await expect(page.getByTestId("approve-ap-1")).toHaveCount(0);
});

test("a failed approvals read renders a retryable alert", async ({ page }) => {
  await page.route("**/api/v1/ai/approvals**", (route) => serverError(route, "approvals unavailable"));
  await gotoApprovals(page);
  await expect(page.getByTestId("error-state")).toBeVisible();
  await expect(page.getByTestId("error-state")).toContainText("approvals unavailable");
});

test("a decided row (non-PENDING tab) offers no buttons", async ({ page }) => {
  await mockApprovalsApi(page, { list: (status) => (status === "APPROVED" ? [decided("APPROVED", { resumed: false })] : []) });
  await gotoApprovals(page);
  await page.getByTestId("approvals-tab-APPROVED").click();
  await expect(page.getByTestId("approval-ap-1")).toBeVisible();
  await expect(page.getByTestId("approval-ap-1")).toContainText("Approved");
  await expect(page.getByTestId("approve-ap-1")).toHaveCount(0);
  await expect(page.getByTestId("deny-ap-1")).toHaveCount(0);
});

test("a queue longer than the page says so instead of reading as complete", async ({ page }) => {
  await mockApprovalsApi(page, { truncated: true });
  await gotoApprovals(page);
  // The rows still render — the notice is about what is NOT on screen.
  await expect(page.getByTestId("approval-ap-1")).toBeVisible();
  await expect(page.getByTestId("approvals-truncated")).toBeVisible();
});

/* ---------------------------------------------------------------- the write */

test("approving posts APPROVED under one key and with NO reason", async ({ page }) => {
  const sent = await mockApprovalsApi(page);
  await gotoApprovals(page);
  await page.getByTestId("approve-ap-1").click();
  await expect(page.getByTestId("decision-dialog")).toBeVisible();
  await page.getByTestId("decision-submit").click();

  expect(sent).toHaveLength(1);
  expect(sent[0].path).toBe("/api/v1/ai/approvals/ap-1/decide");
  expect(JSON.parse(sent[0].body)).toEqual({ decision: "APPROVED" });
  expect(sent[0].body).not.toContain("rejection_reason");
  expect(sent[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  // The row left PENDING, so the refetched queue is empty.
  await expect(page.getByTestId("approvals-empty")).toBeVisible();
});

test("denying posts REJECTED with the reason under the server's field name", async ({ page }) => {
  const sent = await mockApprovalsApi(page);
  await gotoApprovals(page);
  await page.getByTestId("deny-ap-1").click();
  await page.getByTestId("decision-reason").fill("wrong customer");
  await page.getByTestId("decision-submit").click();

  expect(JSON.parse(sent[0].body)).toEqual({ decision: "REJECTED", reason: "wrong customer" });
  // The bug this replaces: the field the server reads is `reason`.
  expect(sent[0].body).not.toContain("rejection_reason");
});

test("a deny with no reason still posts, and sends no empty reason", async ({ page }) => {
  const sent = await mockApprovalsApi(page);
  await gotoApprovals(page);
  await page.getByTestId("deny-ap-1").click();
  await page.getByTestId("decision-submit").click();
  expect(JSON.parse(sent[0].body)).toEqual({ decision: "REJECTED" });
});

test("a replayed decision (400 'already') freezes the dialog: no re-mint, no resend", async ({ page }) => {
  const sent = await mockApprovalsApi(page, { decide: "already" });
  await gotoApprovals(page);
  await page.getByTestId("approve-ap-1").click();
  await page.getByTestId("decision-submit").click();

  const notice = page.getByTestId("decision-terminal");
  await expect(notice).toBeVisible();
  // The server's own sentence is shown by `decision-refused`, which the dialog
  // renders for EVERY refusal — terminal or not — and `decision-terminal` is the
  // block that explains what the screen will now refuse to do. Both are on
  // screen together; pinning the message to the freeze block asked a locator
  // for text the app never puts in it.
  await expect(page.getByTestId("decision-refused")).toContainText("approval already APPROVED");
  await expect(notice).toContainText("This decision cannot be sent");
  await expect(page.getByTestId("decision-submit")).toBeDisabled();
  // A second click must not fire a fresh keyed request — that could grant twice.
  await page.getByTestId("decision-submit").click({ force: true });
  expect(sent).toHaveLength(1);
});

test("a decision attempted without settings:write shows the server's refusal, and stays retryable", async ({ page }) => {
  const sent = await mockApprovalsApi(page, { decide: "forbidden" });
  await gotoApprovals(page);
  await page.getByTestId("approve-ap-1").click();
  await page.getByTestId("decision-submit").click();

  const notice = page.getByTestId("decision-refused");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("missing permission: settings:write");
  // A 403 ran nothing, so unlike the terminal 400 the submit stays enabled...
  await expect(page.getByTestId("decision-submit")).toBeEnabled();
  // ...and a retry reuses the SAME key, because the intent is unchanged.
  await page.getByTestId("decision-submit").click();
  expect(sent).toHaveLength(2);
  expect(sent[1].key).toBe(sent[0].key);
});

/* --------------------------------------------------- the "My Work" approvals */

const SLA = { items: [], timezone: "UTC" };

test("my-work still surfaces pending approvals and their risk level", async ({ page }) => {
  await page.route("**/api/v1/ai/approvals**", (route) => json(route, { items: [PENDING_APPROVAL], truncated: false }));
  await page.route("**/api/v1/sla/risk", (route) => json(route, SLA));
  await page.route("**/api/v1/tasks**", (route) => json(route, []));
  await page.route("**/api/v1/conversations**", (route) => json(route, { items: [], next_cursor: null }));
  await page.route("**/api/v1/platform/saved-views**", (route) => json(route, { items: [] }));

  // Owner IA 2026-09-27: my-work lives ON the overview now (/my-work redirects).
  await page.goto("/dashboard");
  await expect(page.getByText("issue_refund")).toBeVisible();
  await expect(page.getByText(/Risk level:\s*High/)).toBeVisible();
});
