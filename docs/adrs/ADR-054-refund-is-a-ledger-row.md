# ADR-054 — A refund is a ledger row, so refund state is derived and never stored

Date: 2026-09-24. Wave 4 / gaps M1, M3, M6. Evidence: `backend/tests/test_order_refund_ledger.py`
(8), `backend/tests/test_partial_refund_status.py` (14), `backend/tests/test_order_reads.py` (22).
Commits: `18ab160` (ledger, derivation, reads) → `e6ce77a` (CI's Postgres: the actor writing a
refund row has to be a real user) → `504a985` (the screen that finally calls it). Closes gap M1 and
gap M3 in `docs/GAP_REGISTER.md`.

## Context

Three things were true at once, and they contradicted each other:

* `reconcile_payment` could move a **captured** payment to `failed`. Money had been taken, and the
  row said it had not — the reconciliation read as a correction and was in fact a forgery.
* A refund was expressible by that same status word, with no `Refund` row behind it. §57's audit
  story and §66's ledger both assume that money which moved left a record.
* Refunded money kept counting as revenue: `GET /orders/{id}` reported the order `completed`, the
  analytics `revenue` filter summed its gross, and nothing anywhere answered "how much of this is
  still ours?"

The tempting fix was an `orders.status` value — `partial_refunded`, or `refunded` reachable by hand.

## Decisions

### 1. A refund is a row in `refunds`; `Refund(` is constructed in exactly one place

`OrderService.register_refund` (`orders/service.py:1026`) is that place. It takes the order and the
payment under `FOR UPDATE`, refuses anything that is not `captured`/`partially_refunded` (refunding
a pending intent would invent money never taken, `:1052-1057`), quantizes the amount **before**
comparing it to the cap so the arithmetic is about the `NUMERIC(14,2)` rows that will be stored
(`:1059-1061`), sums the payment's existing non-rejected refunds and refuses an overshoot with the
three numbers that prove it (`:1078-1082`).

`reconcile_payment` lost the power to downgrade a captured payment. A payment's status is now moved
by the operations that move money, not by an edit of a word.

### 2. Refund state is derived, so `partial_refunded` was deliberately NOT added to the lifecycle

`orders/money.py:150` `refund_state(settled_gross, refunded)` answers `none | partial | full` from
the payment and refund rows, over the closed `REFUND_STATES` vocabulary (`:102`).

*Why:* `status` answers "where is this order in its life" — the axis `TRANSITIONS` and every status
reader walk. Giving money back does not move the goods: a partially refunded order is still
`shipped`, and `shipped -> partial_refunded -> shipped` is not a lifecycle. A stored flag would be a
second owner of one fact, wrong the moment a refund is rejected or a row corrected by hand.

The derivation's order of tests is the part worth keeping: `refunded <= 0` answers **first**,
because "net is zero, therefore fully returned" reads every unpaid draft as fully refunded. An
overshoot is `full`, never a negative order.

### 3. Revenue reads net, and the overshoot is surfaced rather than clamped away

`analytics/service.py::net_of()` (`:135`) floors refunded money at zero for the balance and
reports the excess as `refund_excess` — a merchant whose refunds exceed collections must see that
as a number, not have it silently absorbed. The status filters behind `revenue`, `net_revenue`,
`refunded_amount` and `aov` are rendered from `MetricRegistry`'s own definitions (`_status_sql`,
`:88`) rather than a second hand-written `WHERE`, so a metric cannot mean two things in two
queries.

### 4. `refunded` remains a status, and it is only reachable by the operation that moved the money

A fully refunded `completed` order transitions to `refunded` inside `register_refund`
(`service.py:1103-1106`) — the same rule §139 already enforced for a manual move: a status that
asserts something about money may only be reached by the code that moves the money. `change_status`
refuses it as a hand entry.

### 5. Customer worth follows the ledger, on the order's current owner

`_recompute_lifetime_value` is called from `add_payment`, `reconcile_payment` and
`register_refund` (gap M6) — one raw-SQL recompute off the ledger rows, on whoever owns the order
**now**. Charging a refund against whoever held the order when it was paid is an accusation the
data does not support.

## Consequences

`GET /orders/{id}` carries `refund_state`, `refunded_total` and `net_collected` beside `status`, so
a screen can say "completed, 25 of it given back" without the money overwriting where the parcel is
(`router.py:87-96`). `order.refunded` goes on the bus in the same transaction as the row.

The order-operations dialog (`frontend/src/components/orders/refund-dialog.tsx`, `504a985`) inherits
a limit from this decision rather than causing it: `GET /orders/{id}/payments` does not expose the
refunds registered against a payment, so for a `partially_refunded` capture the remainder is
**unknown** and the client claims no cap — it lets the server's 409 speak. Inventing `amount − 0`
would have blocked a legal refund or waved through a too-large one.

## Rejected

* **`orders.status = partial_refunded`** — a lifecycle word for a money fact (§2).
* **`refunded_amount` as a column on the order** — a cache of a sum across rows that can be
  corrected by hand, i.e. a second owner of one fact.
* **Reusing `reconcile_payment` to record a refund** — the route that made the forgery possible.
* **Clamping the cap client-side and trusting it** — the client cannot see the ledger's total, so
  the check belongs where the rows are locked.
