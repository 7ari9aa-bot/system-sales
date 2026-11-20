# Egypt retail: payment, cash drawer and shop profiles (design)

Status: **proposal** (awaiting owner review). Scope for this phase: **Egypt + clothing only**.
Other countries and business profiles come later and must not be built now.

## 1. Decision being reversed

`pos/service.py` states the cashier "does not take payment or move money: no tender, no change,
no drawer count". The owner has decided this is reversed: the cashier **records tender, change
and the cash drawer**, and every part of it is switchable per shop. Payment stays a **record of
how the customer paid**, not a payment gateway. No card or wallet processing is built.

Much of the foundation is still in the code (it was switched off, not deleted):

| Existing piece | State |
|---|---|
| `pos_profiles.allowed_payment_methods`, `default_payment_method` | present, unused by sales |
| `pos_cash_movements` (append-only, reasons `cash_sale`, `cash_refund`, `pay_in`, `pay_out`, `cash_drop`, `float_adjust`) | present, read as history |
| `pos_sessions.opening_float / counted_cash / expected_cash / variance` | present |
| `pos_session_reconciliations`, `pos_session_handovers`, `pos_session_floats` | present |
| `OrderService.add_payment` (methods cash, card, wallet, bank_transfer, cod, manual) | present, enforces over-payment guard |
| `OrderService.confirm_sale` (sale without payment) | present, used by the cashier today |

## 2. Shop classification: four independent axes

A shop is described by four axes, not by fixed categories. Each axis has a default; the owner can
change any of them later.

### Axis A: how the shop is paid

| Value | Meaning | Behaviour |
|---|---|---|
| `cash_only` | notes and coins only | tender screen shows cash and change only |
| `cash_plus_transfer` | cash + InstaPay / wallet transfer the cashier confirms by hand | method `wallet` / `bank_transfer` with a required reference number |
| `cash_plus_card_terminal` | separate bank card machine, not connected | method `card` with required approval/RRN number; end of day card total to compare with the bank slip |
| `credit_account` | sells on account / instalments | customer required, balance owed, credit limit |
| mixed | any combination | the shop enables a **list** of methods; split tender allowed |

Because the existing column `allowed_payment_methods` is already a list, "mixed" is the normal
case and needs no new table for v1. Method vocabulary stays the closed set in
`orders/service._PAYMENT_METHODS`; `cod` and `manual` are not offered at the counter.

### Axis B: cash handling mode (`cash_mode`)

| Value | Shifts | Float | Drawer count |
|---|---|---|---|
| `none` | no shifts, one open day per register (already supported by `open-day`) | no | no |
| `simple_drawer` | open/close shift | optional opening float | count at close, variance recorded |
| `managed_drawer` | open/close shift + handover | required | count at close, pay-in/out/drop with reason and approval |
| `electronic_drawer` | as managed, plus "open drawer" command on payment | required | as managed |

`electronic_drawer` only adds a hardware signal (print job kick). It is a flag on the register
(`drawer_kick_enabled`), not a different data model.

### Axis C: size (`scale`)

`single` / `team` / `multi_branch` / `chain`. Controls which screens are visible (branches,
warehouses, transfers) and which permissions exist. It never changes data shape: even a single
shop has one implicit branch and one warehouse.

### Axis D: tax regime (`tax_regime`)

`not_registered` / `receipt_required` (consumer e-receipt) / `invoice_required` (B2B e-invoice)
/ `mixed`. Drives whether ETA submission is on (section 6). The shop owner confirms this with
their tax registration number; the system never guesses it.

## 3. Owner control: three independent layers per feature

1. **Plan entitlement**: is the feature part of the shop's subscription?
2. **Shop setting**: has the owner switched it on?
3. **User permission**: may this employee use it?

A feature is usable only when all three say yes. They live in three places and are never merged.
New table `shop_feature_settings` (tenant_id, key, enabled, params JSONB, updated_by, updated_at)
holds layer 2. Layer 1 and 3 reuse the existing plan and permission code.

Settings with consequences that are hard to undo (batches, serials, costing method) get a
"cannot be turned off once movements exist" rule, enforced in the service.

### Onboarding

Five questions set the defaults (all editable afterwards):
1. How do customers pay? (multi-select, Axis A)
2. Do you use a cash drawer? (Axis B)
3. How many branches / staff? (Axis C)
4. Are you required to issue electronic receipts? Tax number. (Axis D)
5. Business type: clothing (only option in v1).

## 4. Data changes (new Alembic migration, one file)

All new tables are tenant-scoped with row level security, like the rest of the module.

```
pos_profiles           + cash_mode        varchar(20) default 'simple_drawer'
                       + require_manager_for_refund boolean default false
                       + refund_approval_threshold numeric(12,2) null
pos_registers          + drawer_kick_enabled boolean default false
shop_settings          (tenant_id unique, payment_profile, cash_mode, scale, tax_regime,
                        business_profile default 'clothing', updated_at)
shop_feature_settings  (tenant_id, key, enabled, params jsonb) unique(tenant_id, key)
pos_receipt_payments   (id, tenant_id, receipt_id fk, order_payment_id fk, method,
                        amount, tendered numeric, change_given numeric, reference varchar(63))
```

`tendered` and `change_given` exist only for cash; for every other method `reference` is the
approval or transfer number and is required when the shop setting says so.

## 5. Behaviour changes in `PosService`

1. `record_sale` accepts `payments: [{method, amount, tendered?, reference?}]`.
   - Methods must be inside the profile's `allowed_payment_methods`.
   - Sum of non-cash amounts must not exceed the total; cash may exceed it (change).
   - If `payments` is empty and the shop has `cash_mode = none` and `credit_account` is off,
     the sale is recorded without payment, exactly as today (backwards compatible).
2. For each payment call `OrderService.add_payment` (keeps over-payment guard and reservation
   conversion), then, **only for cash**, append a `pos_cash_movements` row with reason
   `cash_sale` for the net cash kept (tendered minus change). Same transaction, same outbox event.
3. Returns and exchanges: refund method defaults to the original method; cash refunds append a
   `cash_refund` movement; exchange difference is charged or refunded through the same path.
   Refunds above the profile threshold require `pos:override`.
4. Session close: `expected_cash = opening_float + cash_sale - cash_refund + pay_in - pay_out -
   cash_drop`, computed from rows (never stored by hand), variance recorded as today.
5. Per method totals at close (cash, card, transfer, wallet) for the bank comparison.

Rules from the repository stay: services only `flush()`, outbox in the same transaction, no
router writes rows, every change has a test that fails before it and passes after.

## 6. ETA e-receipt (wiring, not a rewrite)

The `einvoice` module already contains an ETA provider, document model, hash chain and device
table, but is **not registered** in `app/main.py` and no cashier receipt calls it.

Plan:
1. Register the module's router (read endpoints first), behind the shop feature `eta_receipts`.
2. When `tax_regime` is `receipt_required` or `mixed`, `PosService._issue_receipt` queues an
   `einvoice.submit` outbox event in the same transaction. A worker submits it. A failure never
   blocks the sale: the receipt is marked `pending_submission` and retried; the ETA rule is
   submission within 24 hours.
3. Returns create a return receipt that references the original ETA receipt.
4. One ETA device per register. The activity code for a clothing shop is 4751. Item codes
   (GS1 / EGS) are stored per variant; a missing code blocks only ETA submission, not the sale
   (the shop is warned).
5. Sandbox first (the sandbox provider exists). Production credentials are entered by the shop
   owner in settings and are never stored in the repository.

Open verification items (not confirmed from official sources): the exact small-shop threshold
and deadlines, and whether an intermediary is allowed. These must be checked on the ETA portal
before turning this on for a real shop.

## 7. Clothing layer (next phase, listed so the design does not block it)

Seasons / collections, barcode label printing, parent product with size x colour matrix
editor. The variant model and barcode per variant already exist.

## 8. Offline and numbering (next phase)

Per register number ranges (`prefix + register code + counter`), idempotency key on every sale
request, local queue in the browser, reservation of the last units. Not started in this phase;
the numbering change is the only part that touches the schema early, so the prefix column is
reserved in the migration of the offline phase.

## 9. Order of work and acceptance

| Step | Output | Done when |
|---|---|---|
| 1 | This document reviewed by the owner | owner approves or edits |
| 2 | Migration + models + `shop_settings` service | CI green, RLS test passes |
| 3 | Payment and drawer in `PosService` | new tests: split tender, change, cash refund, close variance |
| 4 | Settings API + frontend toggles | each axis changes behaviour in a test |
| 5 | ETA wiring behind feature flag | sandbox submission test passes |

Nothing here is merged to `main` without a green CI run and the owner's review.
