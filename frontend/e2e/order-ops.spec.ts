import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { json, mockShell, seedAuth, seedLang } from "./support";
import { ApiError } from "../src/lib/api";
import {
  RETURN_REASONS,
  buildCancelBody,
  buildRefundPayload,
  buildReturnBody,
  buildShippingPayload,
  classifyWriteError,
  parseAddressJson,
  refundCapMinor,
  renderAddressJson,
} from "../src/components/orders/order-ops";
import { parseMoney, priceMinor, renderMinor, STORAGE_SCALE } from "../src/components/orders/money";

/* Wave 4's order operations surface, on the client.
 *
 * CI-ONLY PROOF. This sandbox cannot bind a TCP port, so no browser ever ran
 * these specs here — the same caveat `order-money.spec.ts` states. What IS
 * verifiable without a runner is the pure module the dialogs import: the node
 * worker cases at the top never touch `page`, so they run in Playwright's node
 * worker and pin the money and request rules the UI is built on. The rest of
 * the file is browser-only and pins the wiring.
 *
 * Every mocked response is transcribed from
 * `backend/app/modules/orders/router.py` — field names, shapes and codes
 * included, because a spec that mocks a shape the server does not answer proves
 * nothing:
 *
 *   GET   /orders/{id}                                 money position + ETag
 *                                                      + shipping destination
 *   GET   /orders/{id}/payments                        [_payment_out]
 *   GET   /orders/{id}/status-history                  [_history_out]
 *   POST  /orders/{id}/payments/{pid}/refunds {amount, reason} -> 201
 *   POST  /orders/{id}/status           {status, note}         -> {ok: true}
 *   POST  /orders/{id}/return           {reason}               -> {saga_*}
 *   PATCH /orders/{id}/shipping         If-Match, {shipping_*} -> {version}
 *
 * `POST /orders/{id}/cancel` declares NO body and no If-Match, so it cannot
 * carry the reason this screen promises; sending one would be silently dropped.
 * The cancel dialog therefore posts `/status` with `status: "cancelled"` and the
 * note — the only route whose contract answers "cancel with a reason", and the
 * one that releases the reserved stock through the same `change_status` path.
 */

/* ------------------------------------------------------------------ fixtures */

/** `router.get_order`. Money is `str(Decimal)`; `version` is the ETag body.
 *  `shipping_address`/`shipping_method` are the destination the detail read
 *  now answers beside the money (ADR-055's read-surface gap, closed): null
 *  here means the order never had one — the shape `create_order` stores. */
const ORDER_PROCESSING = {
  id: "o1",
  number: "ORD-1001",
  status: "processing",
  version: 3,
  grand_total: "250.00",
  currency: "EGP",
  refund_state: "none",
  refunded_total: "0.00",
  net_collected: "250.00",
  shipping_address: null as Record<string, unknown> | null,
  shipping_method: null as string | null,
  items: [
    { id: "li-1", title: "Coffee Beans", sku: "CB-250", quantity: 2, unit_price: "120.00", total: "240.00" },
  ],
};

/** The same order AFTER a correction stored a destination: what the shipping
 *  dialog must open with, because its own PATCH would replace it whole. */
const ORDER_WITH_DESTINATION = {
  ...ORDER_PROCESSING,
  shipping_address: { city: "Cairo", street: "Tahrir 9" },
  shipping_method: "courier",
};

/** A parcel that left: the goods axis is the live one, the lifecycle says so. */
const ORDER_SHIPPED = { ...ORDER_PROCESSING, status: "shipped", version: 5 };

/** The two axes side by side: still `delivered`, 25 of it given back. */
const ORDER_PARTIALLY_REFUNDED = {
  ...ORDER_PROCESSING,
  status: "delivered",
  refund_state: "partial",
  refunded_total: "25.00",
  net_collected: "225.00",
};

/** `router._payment_out` — `provider`, `provider_ref`, `paid_at` are nullable. */
const PAYMENT_CAPTURED = {
  id: "pay-1",
  order_id: "o1",
  method: "cash",
  status: "captured",
  amount: "250.00",
  currency: "EGP",
  provider: null,
  provider_ref: null,
  paid_at: "2026-09-19T09:05:00Z",
  created_at: "2026-09-19T09:04:00Z",
};

const PAYMENT_PENDING = {
  ...PAYMENT_CAPTURED,
  id: "pay-2",
  method: "card",
  status: "pending",
  provider: "paymob",
  provider_ref: null,
  paid_at: null,
};

/** `router._history_out` — `from_status`, `changed_by_user_id`, `note` nullable. */
const HISTORY = [
  {
    id: "h-1",
    order_id: "o1",
    from_status: null,
    to_status: "pending",
    changed_by_user_id: null,
    note: null,
    created_at: "2026-09-19T09:00:00Z",
  },
  {
    id: "h-2",
    order_id: "o1",
    from_status: "pending",
    to_status: "confirmed",
    changed_by_user_id: "user-1",
    note: "phone confirmed",
    created_at: "2026-09-19T09:02:00Z",
  },
];

const REFUND_CREATED = { id: "rf-1", status: "processed", amount: "25.00" };
const RETURN_OK = { ok: true, saga_id: "saga-1", saga_status: "completed", order_status: "returned" };
const SHIPPING_SAVED = {
  id: "o1",
  number: "ORD-1001",
  status: "processing",
  version: 4,
  shipping_address: { city: "Cairo" },
  shipping_method: "courier",
};

/** The guard's 409 (`core/idempotency._emit_error`), verbatim. */
const IDEMPOTENT_CONFLICT = {
  error: {
    code: "conflict",
    message: "Idempotency-Key reused with a different request body",
    retryable: false,
  },
};
/** `service.register_refund`'s business refusal — also a 409, also terminal. */
const OVER_REFUND = {
  error: {
    code: "conflict",
    message: "refund exceeds captured amount: refunded=0.00, requested=300.00, captured=250.00",
    retryable: false,
  },
};
/** `require_permission("orders:write")` → 403 (`core/errors.PermissionDeniedError`). */
const FORBIDDEN = {
  error: { code: "permission_denied", message: "missing permission: orders:write", retryable: false },
};
/** A stale `If-Match` (`apply_versioned_update` → ConflictError). */
const VERSION_CONFLICT = {
  error: {
    code: "conflict",
    message: "resource version conflict — it changed since you read it",
    retryable: false,
  },
};

/* ------------------------------------------------------------------- routing */

type Sent = {
  method: string;
  path: string;
  body: string;
  key: string | null;
  ifMatch: string | null;
};

type WriteOutcome = "ok" | "conflict" | "over" | "forbidden" | "reject" | "server_error" | "stale";

type Answers = {
  detail?: typeof ORDER_PROCESSING;
  detailFail?: number;
  payments?: unknown[];
  paymentsFail?: number;
  history?: unknown[];
  refund?: WriteOutcome | ((attempt: number) => WriteOutcome);
  /** What the `POST /orders/{id}/status` route answers (the cancel path). */
  status?: WriteOutcome | ((attempt: number) => WriteOutcome);
  ret?: WriteOutcome;
  shipping?: WriteOutcome | ((attempt: number) => WriteOutcome);
  /** Simulate a concurrent writer between the read and the PATCH. */
  bumpVersionOnStale?: boolean;
};

const writePath = (s: Sent, suffix: string) => s.method === "POST" && s.path.endsWith(suffix);

function outcomeOf(
  answer: WriteOutcome | ((attempt: number) => WriteOutcome) | undefined,
  attempt: number,
): WriteOutcome {
  if (answer === undefined) return "ok";
  return typeof answer === "function" ? answer(attempt) : answer;
}

/** Mock every order route the detail screen touches, dispatching on method and
 *  path so a test can assert exactly which route a dialog chose, and answer a
 *  successful write by mutating what the reads return afterwards — which is
 *  how the invalidation assertions below mean something. */
async function mockOrderApi(page: Page, answers: Answers = {}): Promise<Sent[]> {
  const sent: Sent[] = [];
  const state = {
    detail: { ...(answers.detail ?? ORDER_PROCESSING) },
    refunds: 0,
    cancelled: false,
    returned: false,
    versionBumped: false,
  };

  const readDetail = () => {
    const base = { ...state.detail };
    if (state.refunds > 0) return { ...base, ...strip(ORDER_PARTIALLY_REFUNDED, base) };
    if (state.returned) return { ...base, status: "returned", version: base.version + 1 };
    if (state.cancelled) return { ...base, status: "cancelled", version: base.version + 1 };
    if (state.versionBumped) return { ...base, version: base.version + 1 };
    return base;
  };
  /** Keep the fixture's money position consistent with what was refunded. */
  function strip(ref: typeof ORDER_PARTIALLY_REFUNDED, base: typeof ORDER_PROCESSING) {
    return {
      ...base,
      refund_state: ref.refund_state,
      refunded_total: ref.refunded_total,
      net_collected: ref.net_collected,
      version: base.version + 1,
    };
  }

  const record = (route: Route): Sent => {
    const request = route.request();
    const entry: Sent = {
      method: request.method(),
      path: new URL(request.url()).pathname,
      body: request.postData() ?? "",
      key: request.headers()["idempotency-key"] ?? null,
      ifMatch: request.headers()["if-match"] ?? null,
    };
    sent.push(entry);
    return entry;
  };

  const failOr = (route: Route, outcome: WriteOutcome, ok: () => unknown, status = 200) => {
    if (outcome === "conflict") return json(route, IDEMPOTENT_CONFLICT, 409);
    if (outcome === "over") return json(route, OVER_REFUND, 409);
    if (outcome === "forbidden") return json(route, FORBIDDEN, 403);
    if (outcome === "reject")
      return json(
        route,
        { error: { code: "validation_error", message: "amount must be greater than zero", retryable: false } },
        400,
      );
    if (outcome === "server_error")
      return json(route, { error: { code: "internal", message: "upstream failure", retryable: true } }, 500);
    if (outcome === "stale") {
      if (answers.bumpVersionOnStale) state.versionBumped = true;
      return json(route, VERSION_CONFLICT, 409);
    }
    return json(route, ok(), status);
  };

  await page.route("**/api/v1/orders**", (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;
    const sub = path.replace(/^\/api\/v1\/orders\/[^/]+\/?/, "").replace(/\/$/, "");

    // GET /orders — the list this screen links back to (and reads customer_id
    // from, because the detail route does not answer it).
    if (method === "GET" && path === "/api/v1/orders") {
      return json(route, {
        items: [
          {
            id: "o1",
            number: "ORD-1001",
            customer_id: "cust-1",
            status: "processing",
            grand_total: "250.00",
            currency: "EGP",
            placed_at: "2026-09-19T09:00:00Z",
            created_at: "2026-09-19T09:00:00Z",
          },
        ],
        next_cursor: null,
      });
    }
    if (method === "GET" && !path.endsWith("/orders") && !sub) {
      if (answers.detailFail)
        return json(route, { error: { message: "order read failed" } }, answers.detailFail);
      const detail = readDetail();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(detail),
        headers: { etag: `"${detail.version}"` },
      });
    }
    if (method === "GET" && sub === "payments") {
      if (answers.paymentsFail)
        return json(route, { error: { message: "payments unavailable" } }, answers.paymentsFail);
      return json(route, answers.payments ?? [PAYMENT_CAPTURED]);
    }
    if (method === "GET" && sub === "status-history") {
      return json(route, answers.history ?? HISTORY);
    }
    if (sub.endsWith("/refunds") && method === "POST") {
      record(route);
      const outcome = outcomeOf(answers.refund, sent.filter((s) => writePath(s, "/refunds")).length);
      if (outcome !== "ok") return failOr(route, outcome, () => REFUND_CREATED, 201);
      state.refunds += 1;
      return json(route, REFUND_CREATED, 201);
    }
    if ((sub === "status" || sub === "cancel") && method === "POST") {
      record(route);
      const outcome = outcomeOf(answers.status, sent.filter((s) => writePath(s, "/status")).length);
      if (outcome !== "ok") return failOr(route, outcome, () => ({ ok: true }));
      state.cancelled = true;
      return json(route, { ok: true });
    }
    if (sub === "return" && method === "POST") {
      record(route);
      const outcome = outcomeOf(answers.ret, 1);
      if (outcome !== "ok")
        return failOr(route, outcome, () => RETURN_OK);
      state.returned = true;
      return json(route, RETURN_OK);
    }
    if (sub === "shipping" && method === "PATCH") {
      record(route);
      const outcome = outcomeOf(answers.shipping, sent.filter((s) => s.method === "PATCH").length);
      if (outcome !== "ok") return failOr(route, outcome, () => SHIPPING_SAVED);
      // The row keeps the destination the PATCH stored, not just its version:
      // a dialog re-opened after a save must prefill from what landed.
      state.detail = {
        ...state.detail,
        version: SHIPPING_SAVED.version,
        shipping_address: SHIPPING_SAVED.shipping_address,
        shipping_method: SHIPPING_SAVED.shipping_method,
      };
      return json(route, SHIPPING_SAVED);
    }
    return json(route, {});
  });

  return sent;
}

const refundsOn = (sent: Sent[]) => sent.filter((s) => writePath(s, "/refunds"));

async function gotoOrder(page: Page, id = "o1") {
  await page.goto(`/orders/${id}`);
}

async function openRefund(page: Page, paymentId = "pay-1") {
  await page.getByTestId(`refund-payment-${paymentId}`).click();
  await expect(page.getByTestId("refund-dialog")).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await seedAuth(page);
  await mockShell(page);
  await seedLang(page, "en");
});

/* ------------------------------------------- the pure module (node worker) -- */

test("a refund amount is a Decimal STRING on the wire, never a JSON number", () => {
  const built = buildRefundPayload({ amount: "25.5", reason: "Damaged on arrival" }, { scale: 2, capMinor: null });
  expect(built.ok).toBe(true);
  if (!built.ok) throw new Error(`refund refused: ${built.error}`);
  expect(JSON.stringify(built.body)).toBe('{"amount":"25.50","reason":"Damaged on arrival"}');
  // The float pair the storage scale exists for: 0.70 must not widen.
  const seventies = buildRefundPayload({ amount: "0.70", reason: "" }, { scale: 2, capMinor: null });
  expect(seventies.ok && JSON.stringify(seventies.body)).toBe('{"amount":"0.70"}');
});

test("a refund refuses what the server refuses, and says which rule broke", () => {
  for (const text of ["", "-5", "+5", "abc", "1.234", "1e3", "١٢٣", "Infinity"]) {
    expect(buildRefundPayload({ amount: text, reason: "" }, { scale: 2, capMinor: null }).ok, `${text} refused`).toBe(
      false,
    );
  }
  // Zero is not a refund: `RefundCreateRequest` is `gt=0`, unlike a discount.
  const zero = buildRefundPayload({ amount: "0", reason: "" }, { scale: 2, capMinor: null });
  expect(zero.ok).toBe(false);
  if (!zero.ok) expect(zero.error).toBe("zero");
  const tooPrecise = buildRefundPayload({ amount: "1.234", reason: "" }, { scale: 2, capMinor: null });
  expect(!tooPrecise.ok && tooPrecise.error).toBe("too_precise");
});

test("the refund cap is claimed only where the ledger makes it computable", () => {
  expect(refundCapMinor({ status: "captured", amount: "250.00" })).toBe(priceMinor("250.00"));
  // A partially refunded capture has no per-payment refund total on the read, so
  // the client must not invent a remainder: the server's 409 is the authority.
  expect(refundCapMinor({ status: "partially_refunded", amount: "250.00" })).toBeNull();
  expect(refundCapMinor({ status: "pending", amount: "250.00" })).toBeNull();
  expect(refundCapMinor({ status: "refunded", amount: "250.00" })).toBeNull();

  const cap = refundCapMinor({ status: "captured", amount: "250.00" })!;
  const over = buildRefundPayload({ amount: "300.00", reason: "" }, { scale: 2, capMinor: cap });
  expect(over.ok).toBe(false);
  if (!over.ok) expect(over.error).toBe("over_captured");
  // Exactly the captured amount is a full refund and is allowed.
  expect(buildRefundPayload({ amount: "250.00", reason: "" }, { scale: 2, capMinor: cap }).ok).toBe(true);
});

test("a refund reason is capped at the column that stores it", () => {
  const built = buildRefundPayload({ amount: "10.00", reason: "x".repeat(513) }, { scale: 2, capMinor: null });
  expect(built.ok).toBe(false);
  if (!built.ok) expect(built.error).toBe("reason_too_long");
});

test("cancel carries its reason as a note the history table can hold", () => {
  expect(JSON.stringify(buildCancelBody("Customer asked to stop it"))).toBe(
    '{"status":"cancelled","note":"Customer asked to stop it"}',
  );
  // An untouched note is ABSENT, not "": the column is nullable and an empty
  // string would read as "a note was written, and it said nothing".
  expect(JSON.stringify(buildCancelBody("   "))).toBe('{"status":"cancelled"}');
  // `order_status_history.note` is String(512) while `StatusChangeRequest.note`
  // has no max_length, so a longer note is refused here, not at the database.
  expect(buildCancelBody("x".repeat(513)).note).toBeUndefined();
});

test("a return reason is the server's closed vocabulary, never free text", () => {
  // `returns.RETURN_REASONS`; anything else is a ValidationError(400) upstream.
  expect(RETURN_REASONS).toEqual(["customer_return", "delivery_failed"]);
  expect(JSON.stringify(buildReturnBody("delivery_failed"))).toBe('{"reason":"delivery_failed"}');
});

test("a shipping PATCH sends only what was touched, never a half-parsed object", () => {
  expect(JSON.stringify(buildShippingPayload({ method: "courier", address: "" }).body)).toBe(
    '{"shipping_method":"courier"}',
  );
  // `service.update_shipping` replaces an address WHOLE, so what goes out is the
  // complete object the merchant edited — never a merge the server cannot see.
  expect(buildShippingPayload({ method: "", address: '{"city":"Cairo"}' }).body).toEqual({
    shipping_address: { city: "Cairo" },
  });
  expect(buildShippingPayload({ method: "", address: "" }).error).toBe("nothing_to_change");
  expect(buildShippingPayload({ method: "", address: "{city}" }).error).toBe("invalid_json");
  expect(buildShippingPayload({ method: "", address: "[1,2]" }).error).toBe("not_an_object");
  expect(buildShippingPayload({ method: "x".repeat(32), address: "" }).error).toBe("method_too_long");
  expect(parseAddressJson("null").ok).toBe(false);
});

test("a prefilled shipping form sends only what DIFFERS from the stored destination", () => {
  const baseline = { method: "courier", address: { city: "Cairo", street: "Tahrir 9" } };
  // Untouched prefill is not a change: neither field rides the body.
  const untouched = buildShippingPayload(
    { method: "courier", address: renderAddressJson(baseline.address) },
    baseline,
  );
  expect(untouched.error).toBe("nothing_to_change");
  expect(untouched.body).toEqual({});
  // Re-typing the same object in a different key order is still untouched —
  // `canonicalJson` compares content, because the server compares content too.
  expect(
    buildShippingPayload({ method: "", address: '{"street":"Tahrir 9","city":"Cairo"}' }, baseline).body,
  ).toEqual({});
  // One touched field goes out; the other stays out even though the box shows it.
  expect(
    JSON.stringify(buildShippingPayload({ method: "pickup", address: "" }, baseline).body),
  ).toBe('{"shipping_method":"pickup"}');
  // The blank method means "leave it" (the route cannot express clearing one),
  // and the address field carries the WHOLE replacement, deleted lines included.
  expect(
    buildShippingPayload({ method: "", address: '{"city":"Cairo"}' }, baseline).body,
  ).toEqual({ shipping_address: { city: "Cairo" } });
  // With no baseline the rules the dialog shipped before still hold.
  expect(buildShippingPayload({ method: "courier", address: "" }).body).toEqual({
    shipping_method: "courier",
  });
});

test("a refused write keeps the server's own words and its status class", () => {
  expect(
    classifyWriteError(new ApiError("missing permission: orders:write", { status: 403, code: "permission_denied" })),
  ).toEqual({ kind: "permission", message: "missing permission: orders:write" });
  expect(classifyWriteError(new ApiError("refund exceeds captured amount", { status: 409, code: "conflict" })).kind).toBe(
    "conflict",
  );
  expect(
    classifyWriteError(new ApiError("amount must be greater than zero", { status: 400, code: "validation_error" })),
  ).toEqual({ kind: "refused", message: "amount must be greater than zero" });
  // 412 is the other conditional-write refusal, and means the same thing here.
  expect(classifyWriteError(new ApiError("Precondition Failed", { status: 412 })).kind).toBe("stale");
  expect(classifyWriteError(new ApiError("order o9 not found", { status: 404, code: "not_found" })).kind).toBe("refused");
  // A plain Error (no status) is a transport failure, not a refusal.
  expect(classifyWriteError(new Error("Failed to fetch")).kind).toBe("network");
  expect(classifyWriteError(null).kind).toBe("network");
  // The render path a money string takes: string in, exact string out.
  const parsed = parseMoney("12.5", 2);
  expect(renderMinor(parsed.state === "ok" ? parsed.minor : 0n, STORAGE_SCALE)).toBe("12.50");
});

/* ---------------------------------------------------------------- the reads */

test("the screen reads the money position, the payments and the history", async ({ page }) => {
  await mockOrderApi(page);
  await gotoOrder(page);

  await expect(page.getByTestId("order-detail")).toBeVisible();
  // Three separate figures the SERVER computed, rendered as read: no client-side
  // addition across the two axes.
  await expect(page.getByTestId("order-money-position")).toContainText("250.00 EGP");
  await expect(page.getByTestId("order-refunded-total")).toContainText("0.00 EGP");
  await expect(page.getByTestId("order-net-collected")).toContainText("250.00 EGP");
  await expect(page.getByTestId("order-status")).toContainText("processing");
  await expect(page.getByTestId("order-refund-state")).toContainText("none");
  await expect(page.getByTestId("order-payment-pay-1")).toContainText("250.00 EGP");
  await expect(page.getByTestId("order-payment-pay-1")).toContainText("captured");
  await expect(page.getByTestId("order-history-h-2")).toContainText("phone confirmed");
  await expect(page.getByTestId("order-history-h-2")).toContainText("pending");
});

test("a null renders as a dash — never as 0, 0.00 or \"null\"", async ({ page }) => {
  await mockOrderApi(page, { payments: [PAYMENT_PENDING] });
  await gotoOrder(page);

  const row = page.getByTestId("order-payment-pay-2");
  await expect(row).toBeVisible();
  // provider_ref and paid_at are both null on this pending intent.
  await expect(row).toContainText("—");
  await expect(row).not.toContainText("null");
  await expect(row.getByTestId("payment-paid-at")).toHaveText("—");
  await expect(row.getByTestId("payment-provider-ref")).toHaveText("—");
  // The captured amount is real money and still renders exactly.
  await expect(row.getByTestId("payment-amount")).toHaveText("250.00 EGP");

  // The first history entry has no from_status, no note and no actor.
  const first = page.getByTestId("order-history-h-1");
  await expect(first.getByTestId("history-from")).toHaveText("—");
  await expect(first.getByTestId("history-note")).toHaveText("—");
  await expect(first).not.toContainText("null");
});

test("a refund is offered on a captured payment and not on a pending one", async ({ page }) => {
  await mockOrderApi(page, { payments: [PAYMENT_CAPTURED, PAYMENT_PENDING] });
  await gotoOrder(page);
  await expect(page.getByTestId("refund-payment-pay-1")).toBeEnabled();
  // `register_refund` accepts only captured | partially_refunded.
  await expect(page.getByTestId("refund-payment-pay-2")).toHaveCount(0);
  await expect(page.getByTestId("order-payment-pay-2")).toContainText("cannot be refunded");
});

test("no payments and no history are empty states with a next step", async ({ page }) => {
  await mockOrderApi(page, { payments: [], history: [] });
  await gotoOrder(page);
  await expect(page.getByTestId("order-payments-empty")).toBeVisible();
  await expect(page.getByTestId("order-payments-list")).toHaveCount(0);
  await expect(page.getByTestId("order-history-empty")).toBeVisible();
});

test("each read fails on its own, and a partial outage does not blank the record", async ({ page }) => {
  await mockOrderApi(page, { paymentsFail: 500 });
  await gotoOrder(page);
  await expect(page.getByTestId("order-payments-error")).toBeVisible();
  await expect(page.getByTestId("order-payments-error")).toContainText("payments unavailable");
  await expect(page.getByTestId("order-money-position")).toBeVisible();
  await expect(page.getByTestId("order-history-list")).toBeVisible();
  // With the ledger unreadable, the money actions must not pretend otherwise.
  await expect(page.getByTestId("refund-payment-pay-1")).toHaveCount(0);

  await mockOrderApi(page, { detailFail: 404 });
  await gotoOrder(page);
  await expect(page.getByTestId("order-detail-error")).toBeVisible();
  await expect(page.getByTestId("order-detail-error")).toContainText("order read failed");
});

/* ------------------------------------------------------------------- refunds */

test("refunding a captured payment posts the string amount to that payment's route", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await openRefund(page);

  // The cap the dialog states is the payment's own captured amount.
  await expect(page.getByTestId("refund-captured")).toContainText("250.00 EGP");
  await page.getByTestId("refund-amount").fill("25");
  await page.getByTestId("refund-reason").fill("Damaged on arrival");
  await page.getByTestId("submit-refund").click();

  await expect(page.getByText("Refund recorded", { exact: true })).toBeVisible();
  const posts = refundsOn(sent);
  expect(posts).toHaveLength(1);
  expect(posts[0].path).toBe("/api/v1/orders/o1/payments/pay-1/refunds");
  expect(JSON.parse(posts[0].body)).toEqual({ amount: "25.00", reason: "Damaged on arrival" });
  expect(posts[0].body).toContain('"amount":"25.00"');
  expect(posts[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  // The ledger moved, so the money position is re-read — the mock answers the
  // post-refund position only once the screen actually refetches.
  await expect(page.getByTestId("order-refunded-total")).toContainText("25.00 EGP");
  await expect(page.getByTestId("order-refund-state")).toContainText("partial");
});

test("an amount past the captured payment is blocked locally; where the remainder is not computable, the server's 409 is shown verbatim", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("300.00");
  await expect(page.getByTestId("refund-error")).toBeVisible();
  await expect(page.getByTestId("refund-error")).toContainText("250.00");
  await expect(page.getByTestId("submit-refund")).toBeDisabled();
  expect(refundsOn(sent)).toHaveLength(0);

  // A partially refunded capture: no client remainder exists, so the click goes
  // out and the refusal that comes back is the server's own sentence.
  await mockOrderApi(page, { refund: "over", payments: [{ ...PAYMENT_CAPTURED, status: "partially_refunded" }] });
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("300.00");
  await expect(page.getByTestId("submit-refund")).toBeEnabled();
  await page.getByTestId("submit-refund").click();
  const notice = page.getByTestId("refund-refused");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(
    "refund exceeds captured amount: refunded=0.00, requested=300.00, captured=250.00",
  );
  await expect(notice).not.toContainText("Something went wrong");
});

test("a 409 from a replayed Idempotency-Key stops the dialog: no re-mint, no resend", async ({ page }) => {
  const sent = await mockOrderApi(page, { refund: "conflict" });
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("10.00");
  await page.getByTestId("submit-refund").click();

  const notice = page.getByTestId("refund-conflict");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("Idempotency-Key reused with a different request body");
  // The refund may already have landed: a fresh key could give the money back
  // twice, so the submit is blocked and the draft is kept for a human to read.
  await expect(page.getByTestId("submit-refund")).toBeDisabled();
  await page.getByTestId("submit-refund").click({ force: true });
  await page.getByTestId("refund-amount").fill("11.00");
  const posts = refundsOn(sent);
  expect(posts).toHaveLength(1);
  expect(posts[0].key).toMatch(/^[0-9a-f-]{36}$/);

  // The dialog keeps its key while it is open — so a close-and-reopen is the
  // ONLY way to get a new one, because that is a new intent.
  await page.getByTestId("refund-cancel").click();
  await expect(page.getByTestId("refund-dialog")).toHaveCount(0);
});

test("a corrected retry after a 4xx reuses the same key, as the guard's release rule allows", async ({ page }) => {
  const sent = await mockOrderApi(page, { refund: (attempt) => (attempt === 1 ? "reject" : "ok") });
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("10.00");
  await page.getByTestId("submit-refund").click();
  await expect(page.getByTestId("refund-refused")).toContainText("amount must be greater than zero");
  // The draft survives: the merchant fixes it and retries under the same key.
  await expect(page.getByTestId("refund-amount")).toHaveValue("10.00");
  await page.getByTestId("submit-refund").click();

  const posts = refundsOn(sent);
  expect(posts).toHaveLength(2);
  expect(posts[1].key).toBe(posts[0].key);
});

test("a 5xx keeps the key too, and the guard's terminal 409 then freezes the dialog", async ({ page }) => {
  const sent = await mockOrderApi(page, {
    refund: (attempt) => (attempt === 1 ? "server_error" : "conflict"),
  });
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("10.00");
  await page.getByTestId("submit-refund").click();
  await expect(page.getByTestId("refund-refused")).toContainText("upstream failure");
  await page.getByTestId("submit-refund").click();

  await expect(page.getByTestId("refund-conflict")).toContainText("Idempotency-Key reused");
  const posts = refundsOn(sent);
  expect(posts).toHaveLength(2);
  expect(posts[1].key).toBe(posts[0].key);
});

test("a refund without a reason is allowed, because the server's field is optional", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await openRefund(page);
  await page.getByTestId("refund-amount").fill("5.00");
  await page.getByTestId("submit-refund").click();
  expect(JSON.parse(refundsOn(sent)[0].body)).toEqual({ amount: "5.00" });
});

/* ------------------------------------------------------------------- cancels */

test("cancelling posts its reason where the backend can store it", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await page.getByTestId("cancel-order-btn").click();
  await expect(page.getByTestId("cancel-dialog")).toBeVisible();
  await page.getByTestId("cancel-note").fill("Customer asked to stop it");
  // A note is not an acknowledgement. Cancellation is irreversible, so the
  // submit stays gated on the explicit checkbox whatever the note says — this
  // case is about WHERE the reason goes, so it ticks the box and moves on.
  await page.getByTestId("cancel-confirm-ack").check();
  await page.getByTestId("submit-cancel").click();

  const posts = sent.filter((s) => writePath(s, "/status"));
  expect(posts).toHaveLength(1);
  expect(posts[0].path).toBe("/api/v1/orders/o1/status");
  expect(JSON.parse(posts[0].body)).toEqual({ status: "cancelled", note: "Customer asked to stop it" });
  expect(posts[0].key).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("Order cancelled", { exact: true })).toBeVisible();
  // The screen re-reads, and the row says cancelled.
  await expect(page.getByTestId("order-status")).toContainText("cancelled");
});

test("a cancel with no reason still posts, and sends no empty note", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await page.getByTestId("cancel-order-btn").click();
  // The acknowledgement is the gate on every cancel, with a note or without one;
  // this case is about the BODY, so it leaves the note box empty.
  await page.getByTestId("cancel-confirm-ack").check();
  await page.getByTestId("submit-cancel").click();
  expect(JSON.parse(sent.filter((s) => writePath(s, "/status"))[0].body)).toEqual({ status: "cancelled" });
});

test("a cancel is an irreversible action: the confirmation is the submit, not a blind click", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await page.getByTestId("cancel-order-btn").click();
  await expect(page.getByTestId("cancel-warning")).toBeVisible();
  await page.getByTestId("cancel-note").fill("changed my mind");
  await page.getByTestId("cancel-confirm-ack").check();
  await expect(page.getByTestId("submit-cancel")).toBeEnabled();
  await page.getByTestId("cancel-confirm-ack").uncheck();
  await expect(page.getByTestId("submit-cancel")).toBeDisabled();
  expect(sent.filter((s) => writePath(s, "/status"))).toHaveLength(0);
});

test("a cancel attempted without orders:write shows the server's refusal, and stays retryable", async ({ page }) => {
  await mockOrderApi(page, { status: "forbidden" });
  await gotoOrder(page);
  await page.getByTestId("cancel-order-btn").click();
  await page.getByTestId("cancel-note").fill("nope");
  await page.getByTestId("cancel-confirm-ack").check();
  await page.getByTestId("submit-cancel").click();

  const notice = page.getByTestId("cancel-refused");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("missing permission: orders:write");
  // A 403 ran nothing, so unlike a 409 the dialog is not frozen.
  await expect(page.getByTestId("submit-cancel")).toBeEnabled();
});

test("a 409 on the cancel freezes it too, and the key is not re-minted", async ({ page }) => {
  const sent = await mockOrderApi(page, { status: "conflict" });
  await gotoOrder(page);
  await page.getByTestId("cancel-order-btn").click();
  await page.getByTestId("cancel-confirm-ack").check();
  await page.getByTestId("submit-cancel").click();
  await expect(page.getByTestId("cancel-conflict")).toContainText("Idempotency-Key reused");
  await expect(page.getByTestId("submit-cancel")).toBeDisabled();
  expect(sent.filter((s) => writePath(s, "/status"))).toHaveLength(1);
});

test("cancel, shipping and return are offered where the state machine allows them", async ({ page }) => {
  // shipped: TRANSITIONS has no shipped -> cancelled, and the address is history.
  await mockOrderApi(page, { detail: ORDER_SHIPPED });
  await gotoOrder(page);
  await expect(page.getByTestId("cancel-order-btn")).toHaveCount(0);
  await expect(page.getByTestId("shipping-btn")).toHaveCount(0);
  await expect(page.getByTestId("return-order-btn")).toBeEnabled();
  // The MONEY axis is independent of the goods axis: a shipped order with a
  // captured payment can still be refunded.
  await expect(page.getByTestId("refund-payment-pay-1")).toBeEnabled();

  // delivered: returnable, not cancellable, not addressable.
  await mockOrderApi(page, { detail: { ...ORDER_SHIPPED, status: "delivered" } });
  await gotoOrder(page);
  await expect(page.getByTestId("return-order-btn")).toBeEnabled();
  await expect(page.getByTestId("cancel-order-btn")).toHaveCount(0);
  await expect(page.getByTestId("shipping-btn")).toHaveCount(0);

  // cancelled: nothing is offered; the reason from the history is what remains.
  await mockOrderApi(page, { detail: { ...ORDER_PROCESSING, status: "cancelled" } });
  await gotoOrder(page);
  await expect(page.getByTestId("cancel-order-btn")).toHaveCount(0);
  await expect(page.getByTestId("return-order-btn")).toHaveCount(0);
  await expect(page.getByTestId("shipping-btn")).toHaveCount(0);
});

/* ------------------------------------------------------------------- returns */

test("returning an order restocks through the saga and reports which saga answered", async ({ page }) => {
  const sent = await mockOrderApi(page, { detail: ORDER_SHIPPED });
  await gotoOrder(page);
  await page.getByTestId("return-order-btn").click();
  await expect(page.getByTestId("return-dialog")).toBeVisible();
  await page.getByTestId("return-reason").selectOption("delivery_failed");
  await page.getByTestId("submit-return").click();

  const posts = sent.filter((s) => writePath(s, "/return"));
  expect(posts).toHaveLength(1);
  expect(posts[0].path).toBe("/api/v1/orders/o1/return");
  expect(JSON.parse(posts[0].body)).toEqual({ reason: "delivery_failed" });
  expect(posts[0].key).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("Order returned", { exact: true })).toBeVisible();
  // Money is NOT a return step (ADR-052), so the dialog has to say so.
  await expect(page.getByTestId("return-money-note")).toBeVisible();
});

test("a return the process refuses shows the server's sentence, not a shrug", async ({ page }) => {
  await mockOrderApi(page, { detail: ORDER_SHIPPED, ret: "over" });
  await gotoOrder(page);
  await page.getByTestId("return-order-btn").click();
  await page.getByTestId("submit-return").click();
  const notice = page.getByTestId("return-refused");
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("refund exceeds captured amount");
  await expect(notice).not.toContainText("Something went wrong");
});

test("a return whose reason the server does not know is a 400, and the vocabulary is fixed locally", async ({ page }) => {
  await mockOrderApi(page, { detail: ORDER_SHIPPED, ret: "reject" });
  await gotoOrder(page);
  await page.getByTestId("return-order-btn").click();
  // Exactly the two reasons `returns.RETURN_REASONS` allows, and no free text.
  await expect(page.getByTestId("return-reason").locator("option")).toHaveCount(2);
  await page.getByTestId("submit-return").click();
  await expect(page.getByTestId("return-refused")).toContainText("amount must be greater than zero");
});

/* -------------------------------------------------- the versioned shipping */

test("the shipping PATCH sends the version it read; a stale write is re-read, not forced", async ({ page }) => {
  const sent = await mockOrderApi(page, {
    shipping: (attempt) => (attempt === 1 ? "stale" : "ok"),
    bumpVersionOnStale: true,
  });
  await gotoOrder(page);
  await page.getByTestId("shipping-btn").click();
  await expect(page.getByTestId("shipping-dialog")).toBeVisible();
  await page.getByTestId("shipping-method").fill("courier");
  await page.getByTestId("submit-shipping").click();

  const patched = sent.filter((s) => s.method === "PATCH");
  expect(patched).toHaveLength(1);
  expect(patched[0].path).toBe("/api/v1/orders/o1/shipping");
  // The version from the detail read, as a token `parse_if_match` accepts.
  expect(patched[0].ifMatch).toBe("3");
  expect(JSON.parse(patched[0].body)).toEqual({ shipping_method: "courier" });

  const stale = page.getByTestId("shipping-stale");
  await expect(stale).toBeVisible();
  await expect(stale).toContainText("it changed since you read it");
  // The rule: a 409/412 means re-read, so the submit is blocked while the write
  // the merchant meant would land on top of someone else's change.
  await expect(page.getByTestId("submit-shipping")).toBeDisabled();

  await page.getByTestId("shipping-reread").click();
  await expect(page.getByTestId("shipping-stale")).toHaveCount(0);
  await expect(page.getByTestId("submit-shipping")).toBeEnabled();
  await page.getByTestId("submit-shipping").click();

  const after = sent.filter((s) => s.method === "PATCH");
  expect(after).toHaveLength(2);
  expect(after[1].ifMatch).toBe("4");
  // A versioned PATCH is not a keyed write: the CAS is the retry control
  // (`service.update_shipping` says so, and `apply_versioned_update` enforces it).
  expect(after[1].key).toBeNull();
});

test("an untouched shipping form cannot be submitted — the server refuses an empty PATCH", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await page.getByTestId("shipping-btn").click();
  // Case-sensitive match: the English label opens with a capital, and a
  // lowercase probe here would silently assert nothing.
  await expect(page.getByTestId("shipping-error")).toContainText("Nothing to change");
  await expect(page.getByTestId("submit-shipping")).toBeDisabled();
  await page.getByTestId("shipping-address").fill("{oops}");
  await expect(page.getByTestId("shipping-error")).toContainText("not valid JSON");
  await expect(page.getByTestId("submit-shipping")).toBeDisabled();
  expect(sent.filter((s) => s.method === "PATCH")).toHaveLength(0);
});

test("the shipping dialog opens prefilled, and only the touched line is submitted", async ({ page }) => {
  const sent = await mockOrderApi(page, { detail: ORDER_WITH_DESTINATION });
  await gotoOrder(page);
  await page.getByTestId("shipping-btn").click();
  await expect(page.getByTestId("shipping-dialog")).toBeVisible();

  // The gap ADR-055 closed: a whole-replacement write must show every line its
  // submit would delete. The stored destination is IN the boxes, not behind them.
  await expect(page.getByTestId("shipping-method")).toHaveValue("courier");
  const prefilled = await page.getByTestId("shipping-address").inputValue();
  expect(JSON.parse(prefilled)).toEqual({ city: "Cairo", street: "Tahrir 9" });
  // Prefilled is not touched: the submit still refuses to claim a change.
  await expect(page.getByTestId("submit-shipping")).toBeDisabled();
  expect(sent.filter((s) => s.method === "PATCH")).toHaveLength(0);

  // Correct one line — drop the street — and the body carries the WHOLE new
  // address (replace semantics) and nothing else: not the method, not the
  // stored object re-sent under another key.
  await page.getByTestId("shipping-address").fill('{"city":"Cairo"}');
  await expect(page.getByTestId("submit-shipping")).toBeEnabled();
  await page.getByTestId("submit-shipping").click();
  const patched = sent.filter((s) => s.method === "PATCH");
  expect(patched).toHaveLength(1);
  expect(JSON.parse(patched[0].body)).toEqual({ shipping_address: { city: "Cairo" } });
  expect(patched[0].ifMatch).toBe("3");
});

test("a shipping write that lands updates the version the next write must send", async ({ page }) => {
  const sent = await mockOrderApi(page);
  await gotoOrder(page);
  await page.getByTestId("shipping-btn").click();
  await page.getByTestId("shipping-method").fill("courier");
  await page.getByTestId("submit-shipping").click();
  await expect(page.getByText("Shipping updated", { exact: true })).toBeVisible();

  // Wait for the save's close to FINISH before reopening. Radix keeps the
  // content mounted through the 150ms exit animation, and a pointerdown on the
  // trigger inside that window is remembered as an outside-press: it opens the
  // dialog and dismisses it again a frame later (measured: `data-state` goes
  // open → closed 8ms apart, and the reopen is swallowed). The claim below is
  // about the version the next write must send, not about clicking mid-fade.
  await expect(page.getByTestId("shipping-dialog")).toHaveCount(0);

  await page.getByTestId("shipping-btn").click();
  // The write landed, so the re-read's destination is now the prefill: what the
  // row holds after the save is what the next correction opens showing.
  await expect(page.getByTestId("shipping-method")).toHaveValue("courier");
  expect(
    JSON.parse(await page.getByTestId("shipping-address").inputValue()),
  ).toEqual({ city: "Cairo" });
  await page.getByTestId("shipping-method").fill("pickup");
  await page.getByTestId("submit-shipping").click();
  const patched = sent.filter((s) => s.method === "PATCH");
  expect(patched).toHaveLength(2);
  expect(patched[0].ifMatch).toBe("3");
  // The saved version, not the one the screen first read.
  expect(patched[1].ifMatch).toBe("4");
  // And the untouched prefilled address stays out of this body — the next read
  // would still show `{city: "Cairo"}` because this PATCH never claims it.
  expect(JSON.parse(patched[1].body)).toEqual({ shipping_method: "pickup" });
});
