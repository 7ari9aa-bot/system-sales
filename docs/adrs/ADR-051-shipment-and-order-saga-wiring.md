# ADR-051 — Shipments and the order saga move through the paths that already guard them

Date: 2026-09-23. Wave 4 / task W4-T2. Evidence: `backend/tests/test_order_fulfillment.py`
(16 cases; the 14 DB-backed ones verified on CI Postgres), commits `568c456` (RED: 14
failures, 1222 passing otherwise) → `7abcccf` + this fix on `w4-t2-shipment-saga`.

## Context

Two halves of the same gap, both found by reading for callers rather than for names:

1. **`shipments` was migrated and modelled with no writer anywhere.** `TRANSITIONS`
   allowed `processing -> shipped`, so an order could legitimately read `shipped`
   while no row existed to say which carrier took it or what the tracking number
   was. GAP_REGISTER M8 called it a dead table; the dead-table half was really a
   missing operation.
2. **`orders.process_state` (§139) had a validated machine and zero callers**, so the
   column kept its `created` default for every order ever placed — and the machine
   itself could not describe this system's normal order: checkout reserves stock
   *before* any money exists (COD), while `_PROCESS_TRANSITIONS` only allowed
   `created -> paid -> stock_reserved`.

## Decisions

### 1. Shipping an order is one operation, not two records kept in step by hand

`OrderService.create_shipment` requires `processing` and moves the order through
`_transition` — the same guarded path `change_status` uses — then writes the
`Shipment` row. It does not set `order.status` itself.

*Why:* the alternative (insert a shipment, then let the merchant change the status)
leaves the tracking row and the order status as two facts that can disagree, and it
skips the `OrderStatusHistory` row and the outbox event. A rejection from
`TRANSITIONS` then arrives after the shipment is already on disk.

*Consequence:* the event type is the registered `order.status_changed`, not a new
`order.shipped`. The first draft passed `event_type="order.shipped"` and CI refused it
at the envelope registry (`events/schemas.py`): the payload already carries
`from_status`/`to_status`, so a second name for the same fact buys nothing.
`order.cancelled`/`order.refunded` are separate types because they carry stock and
money consequences of their own; shipping does not.

### 2. A carrier "delivered" moves the order too

`set_shipment_status` walks `SHIPMENT_TRANSITIONS` (`pending -> picked_up ->
in_transit -> delivered|returned|failed`, terminals with no exit) and, on
`delivered`, advances `shipped -> delivered` when the order is still at `shipped`.

*Why:* the scan is the evidence that step was always waiting for. `returned` and
`failed` deliberately do **not** move the order: `TRANSITIONS` has no exit from
`shipped` except `delivered`, and inventing one to model a carrier failure would be a
money/stock claim this task has no evidence for. The merchant's next real step
(refund, re-ship) stays explicit.

### 3. The saga advances as a side effect, and side effects never fail their host

`_advance`-style leniency is split from the strict command:

- `transition_process_state` (the human/explicit path) keeps raising `ConflictError`
  for an illegal move.
- `OrderService._saga_move` (used inside `_transition`, `add_payment`,
  `reconcile_payment`) applies the move only when the machine allows it and otherwise
  logs `order.process_state left alone` and returns.

*Why:* the second capture of a split payment is a real, successful event; letting the
bookkeeping of "paid" 409 the capture would make the saga column's strictness damage
the money path. Conversely, an explicit command to move the saga is a human asserting
something, and a wrong assertion must be refused.

### 4. Where each state is written

`created` → the row default. `stock_reserved` → the order row is **born** with it,
because the reserve loop runs before `_insert_order` and aborts the whole order when
stock is short; recording `created` would be a claim the reservations contradict.
`paid` → the capture paths (`add_payment`, `reconcile_payment` reaching `captured`).
`fulfilled` → `_SAGA_ON_STATUS` on `delivered`/`completed`. `cancelled` → on
`cancelled` (so `cancel_order` and `change_status` both reach it through `_transition`).

The saga part of `_transition` is folded into the **same** update statement as the
status: `apply_versioned_update` issues one compare-and-swap UPDATE, and a second
ORM UPDATE for the same row would ride past the `If-Match` guarantee (§17).

### 5. `created -> stock_reserved` and `stock_reserved -> paid` are both legal

Paid-before-picked and picked-before-paid are both real here (card settlement can
follow the pick; COD precedes it), so `paid` and `stock_reserved` are order-independent
and only `fulfilled`/`cancelled` are terminals.

## Consequences

- Shipment rows now have exactly one producer, and it cannot be reached without the
  order's own guarded transition.
- `orders.process_state` stops being a column that only tests write.
- The write routes are RBAC-gated `orders:write`, proven with a 403 through the real
  ASGI stack rather than by introspecting FastAPI's route tree — which turned out to
  nest included routers (`_IncludedRouter`) instead of flattening them, so a
  `app.routes` walk finds nothing under `/api/v1`.
- Still open, deliberately: `app/core/saga.py` and the migrated `sagas` table remain
  unwired (§139's generic orchestrator). With the order saga now on the order row,
  running the same process through both would recreate the two-sources-of-truth
  problem this ADR exists to avoid; the retire-or-use call is tracked as W4-T2b, and
  §139 stays 🟡 in the matrix until it is made.
