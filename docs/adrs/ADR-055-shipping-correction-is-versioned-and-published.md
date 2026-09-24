# ADR-055 — Correcting where an order is going is a versioned write that publishes

Date: 2026-09-24. Wave 4 / gap M8, Wave 5 / the order record. Evidence:
`backend/tests/test_order_shipping_event.py` (8), `backend/tests/test_order_reads.py` (22),
`backend/tests/test_if_match_wave2.py`; on the client, `frontend/e2e/order-ops.spec.ts`.
Commits: `18ab160` (the event, the tier) → `504a985` (the screen and its discipline). Closes the
shipping half of gap M8.

## Context

`PATCH /orders/{id}/shipping` existed and wrote an audit row. Two things were missing, and the
second was discovered only after the first was fixed:

* Nothing downstream could learn about the change. The address a live order is going to is the fact
  a courier label and a routing rule are printed from, and `order.shipping_updated` was not on the
  bus — so the write was visible to a person reading the audit table and invisible to every
  consumer. §19 is not satisfied by a mutation that only one of the two audiences can see.
* The row has a `version`, and the route ignored it. Two staffers correcting the same typo would
  both get a 200, and the second would silently overwrite the first — the check-then-act shape
  Wave C's review kept finding.

## Decisions

### 1. The write is conditional, and the version in the `WHERE` clause is the check

`update_shipping` (`orders/service.py:1295`) locks the row `FOR UPDATE` (`:1317-1319`), fast-fails a
stale `If-Match` through `require_version` **before** touching the audit trail (`:1320-1322`), and
applies its mutation through `apply_versioned_update` — one statement with the expected version in
its `WHERE` clause (`:1353`). The response and the ETag carry the row's post-mutation version
(`router.py:359-364`).

### 2. There is no `Idempotency-Key here, on purpose

`G-14`'s key is opt-in per route, and this route's retry control is the compare-and-set: the version
**is** the answer to "did this already happen". A key would add a second, weaker mechanism over a
write whose conflict semantics are already exact — and after a successful PATCH the row is at its
latest version, so a replay from the same screen cannot silently re-apply an old correction. The
client states the same rule (`frontend/src/components/orders/shipping-dialog.tsx:13-17`).

### 3. A PATCH that changes nothing claims nothing

If the supplied values equal what the row holds, the service returns early (`:1345-1350`): no
version bump, no audit row, no event. Because this route has no key, the retry-safe answer has to
come out of the mutation itself rather than from a dedupe layer.

### 4. `shipping_method` lives in `orders.extra`, and the route says so

`orders` has no `shipping_method` column, and adding one is a migration rather than a side effect of
a correction endpoint; `extra` is this row's own extension JSONB and already carries the warehouse
id the same way (`:1336-1344`). Both the audit `before`/`after` and the response read it from the
same place, so the column that does not exist cannot disagree with the one that does.

### 5. The address is replaced whole, and only touched fields go out

`update_shipping` assigns `shipping_address` rather than merging into it (`:1334-1335`), so a partial
send would delete the parts the form never showed. The client refuses to send a partial:
`buildShippingPayload` emits only fields the merchant actually touched, and the address field takes
the **entire** object the next read must show (`order-ops.ts`, `parseAddressJson`).

### 6. The event carries the previous address, and rides the critical tier

`order.shipping_updated` is staged through the outbox in the same transaction as the row, with the
real `aggregate_version` (§153, `:1371-1390`). `previous_shipping_address` rides along because a
consumer must be able to tell where the parcel WAS going from where it is going, without replaying
the stream to find out. `core/fairness` gives the event the `CRITICAL_SYSTEM` tier — a
money-lifecycle event must not queue behind bulk campaign work (the tier test was verified red
without it).

### 7. What the screen does when the write loses

A 409/412 on this route is not a failure to retry: the dialog blocks the submit and offers a
**re-read** that keeps the merchant's draft and replaces only the version
(`shipping-dialog.tsx:119-141`). Forcing a lost write would overwrite a correction a colleague just
made, which is the exact race §1 exists to prevent.

## Consequences

The status gate stayed where it was: `_SHIPPING_EDITABLE_STATUSES` is `pending/confirmed/processing`
(`:1323-1327`). After `shipped`, the address on the row is history and the next leg is a shipment
record, not a correction — this route is not a redirect tool.

`GET /orders/{id}` does not return the shipping address, so the correction form opens empty and its
own hint says the value replaces what is stored. That is a read-surface gap, not a dishonest screen;
closing it belongs with the order reads, and is recorded in `docs/GAP_REGISTER.md`.

## Rejected

* **Merging the address object** — a merge cannot express "this line is gone".
* **A `shipping_method` column plus migration** — the correction endpoint does not own the schema.
* **An `Idempotency-Key` alongside `If-Match`** — two retry mechanisms on one write, and the
  weaker one would win the argument.
* **Retrying a lost CAS client-side** — that is how a correction becomes an overwrite.
