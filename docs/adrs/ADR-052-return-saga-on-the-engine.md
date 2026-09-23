# ADR-052 — The goods-return process runs on the saga engine

Date: 2026-09-23. Wave 4 / task W4-T2b. Evidence: `backend/tests/test_return_saga.py`
(16 cases; the 14 DB-backed ones verified on CI Postgres). Commits: `e1cf231` (RED,
CI run 35857364838 = 16 failed / 1238 passed) → `5bd4512` (implementation) →
`394b79a` + `19c9229` (the fixture bugs CI's Postgres exposed). Supersedes ADR-051
decision 2 and closes the item ADR-051 left open.

## Context

`app/core/saga.py` (291 lines before this task's two fixes) and the migrated `sagas`
table had no caller of any kind, and were baselined as dead in
`test_no_dead_core_modules.py`. Two readings were
on the table: retire the engine — §139 accepts "a Process Manager/Saga **or** a clear
state machine", and ADR-051 had just delivered the state machine — or give it the one
process that genuinely needs it.

The process that needs it is the return. Since ADR-051 a carrier scanning
`in_transit -> returned` moved the parcel and nothing else: the order stayed `shipped`
forever, the ledger kept its `out`/`sale` row, and the goods were nowhere. §139 names
that half explicitly ("Fulfillment failed → compensation policy"), and it is the only
place in the commerce domain where a step's failure has to be able to demand the undo
of the step before it. Retiring the engine would have meant building that compensation
inline, in the shape of a saga, without a saga.

## Decisions

### 1. Two machines, asked two different questions

`orders.process_state` remains the order's own lifecycle (`created/paid/
stock_reserved/fulfilled/cancelled/returned`). The `sagas` row records one **process**:
which steps ran, in what order, what each returned, and what was undone. It does not
hold a second copy of "where is this order".

*Why:* ADR-051 refused to drive the order lifecycle through both. This does not
repeal that — the return saga never writes an order status except through
`_transition`, and the order row stays authoritative.

### 2. `returned` is a stock claim, so hand-entry is refused

`TRANSITIONS` gained `shipped -> returned`, `delivered -> returned` and
`returned -> refunded`, and `change_status` now rejects a manual move to `returned`
with a pointer to the return process. This mirrors the rule already in that function
for `refunded`: a status that asserts something about money or stock may only be
reached by the operation that actually moves the money or the stock.

### 3. What "restock" means is derived from the reservation, not assumed

A paid line settled its stock (`convert` released the hold **and** decremented
`on_hand` with an `out`/`sale` row). A cash-on-delivery line that shipped without
ever being paid still only **holds** the units — `on_hand` never moved.

So step 0 asks which reservations are still `ACTIVE` per line: a settled line goes
back with an `in`/`return` ledger row; a held line is released, and no `in` movement
is written. Its undo re-takes the shelf units (`out`/`return_reversal`) or re-reserves
them.

*Why:* adding stock for a COD return would invent inventory that was never sold. The
distinction is exactly the one §140's reservation states exist to make.

### 4. A refund is not a step

§115 lists "Refund approval" among the critical flows, so giving money back stays a
decision a human makes on a payment (`register_refund`), never a side effect of a box
arriving at a warehouse. The return saga leaves the money untouched and the order at
`returned`, from which `refunded` remains reachable through the existing money-guarded
path once the merchant holds nothing.

### 5. `returned` is terminal for the process, and one return per order

`RETURNABLE_STATUSES = {shipped, delivered}`; a second attempt 409s, and the refusal
happens **before** the saga row is created, so a wrong click leaves no half-process
behind. `returned` closes the saga machine, and it is reachable from `paid` and
`stock_reserved` as well as `fulfilled` — which parcel comes back before any money
exists (COD) and which after it is the *status* machine's business, but the saga
column has to be able to say "returned" either way.

## The defects the first caller found

An engine nobody runs is an engine nobody has tested. Two were wrong on first use:

- **`step_results` is JSONB and is not mutation-tracked.** `_compensate` edited
  `record["status"] = "compensated"` inside the nested dicts, never dirtying the
  column, so after a real compensation the row still claimed every step had
  completed. Fixed by rebuilding the list and assigning it back
  (`test_the_compensation_result_is_stored_not_just_applied`).
- **`sagas.completed_at` was naive in the model, `WITH TIME ZONE` in the migration.**
  `test_model_and_migration_agree_on_timestamp_timezone` caught it the moment the
  column started being written; the comparison against `created_at` would have raised
  at runtime.
- **A paid order is not where the create call left it, and the test fixture assumed it
  was.** `create_order` returns a `pending` row, but `add_payment` confirms a pending
  order as part of capturing (ADR-051's saga wiring, `service.py:675`) — and because
  SQLAlchemy's identity map hands back the same instance the caller already holds, the
  order object had quietly moved before the fixture's first step. Its walk then asked
  for `confirmed -> confirmed`, which no machine allows. CI Postgres was the first
  place that ran; locally the case skips. The helper now reads the row's live status
  and asserts at the end that it landed where it claimed.
- **The saga machine could not say `returned` about an order that was never
  fulfilled.** ADR-051 wired `_SAGA_ON_STATUS["returned"]` but left `returned`
  reachable only from `fulfilled`, and a returned parcel is usually not fulfilled —
  CI's first green-shipping run produced `status=returned, process_state=paid` on the
  same row, which is the exact two-facts-disagreeing defect this task set out to close.
  The lenient `_saga_move` refused the illegal move silently instead of failing the
  transition, so nothing raised; the column just stayed wrong. `paid` and
  `stock_reserved` now reach `returned` too
  (`test_returned_is_a_state_both_machines_know`).

## Deliberate limits

- The process runs to the end **inside the caller's transaction**, so a hard crash
  rolls the whole thing back and the DB is the last line of undo. The engine's
  compensation is still what makes the *retry* safe — a carrier return arriving again
  through the async ingress path (§22) must not find the first attempt's restock
  standing — and the `failed` saga row is the durable record of what was undone, which
  a rollback alone would not leave behind.
- `execute_next` reads the saga without `FOR UPDATE`. With exactly one synchronous
  driver, which locks the order row first, that is not reachable; a second, worker-
  driven driver must add the lock before it exists.
- `app.core.money` / `partitioning` / `search_indexer` stay baselined dead; this ADR
  decides about the saga engine only.

## Consequences

- §139's compensation half has an implementation and a test, and `core/saga.py` moved
  from `KNOWN_DEAD_CORE_MODULES` to `WIRED_CORE_MODULES`.
- A returned parcel now produces: an `in`/`return` (or released-hold) ledger row per
  line, its reservations CANCELLED, an `OrderStatusHistory` row, the
  `order.status_changed` outbox event, and a `completed` saga row with both step
  results.
- `POST /api/v1/orders/{id}/return` (`orders:write`) is the staff entry point;
  `POST /api/v1/shipments/{id}/status` with `returned`/`failed` runs the same process.
- GAP_REGISTER M8's remaining order-API reads (filters, payments list, status history)
  stay open.
