# Commerce Core Architecture v1.0

**Adopted:** 2026-10-04 · **Decision:** ADR-061 · **Spec anchor:** §178–§190
(`docs/spec/ARCHITECTURE_PATCH_178-200.txt`) · **Status: binding.**

This document formalizes the commerce half of the platform as an independent
Bounded Domain — the **Commerce Core** — with published APIs and explicit
internal boundaries. The Agent Platform (agents, channels, dashboard,
analytics) depends on the Core; the Core depends on nothing above it.

Every claim below was measured against the code on 2026-10-04. Where the code
already implements a rule, the implementing file is cited. Where it does not,
the gap is named and tracked in `docs/GAP_REGISTER.md` (section "Commerce Core
v1.0 audit") — no rule in this document is retroactively declared "done".

---

## 1. Position in the platform

```
                       AGENT PLATFORM (control + runtime)
             Agents / Channels / Dashboard / Analytics consumers
                                   │
                         Capabilities / Application APIs
                                   ▼
╔═══════════════════════════════════════════════════════════════════╗
║                        COMMERCE CORE (bounded)                    ║
║                                                                   ║
║   Catalog Domain      Inventory Domain      Commerce Domain       ║
║   (product truth)     (ledger truth)        (transaction engine)  ║
║          └──────────────────┬──────────────────┘                  ║
║                             ▼                                     ║
║              Transaction / Invariant Enforcement                  ║
║     idempotency · locking · preconditions · state transitions     ║
║              tenant isolation · audit references                  ║
║                             │                                     ║
║        POS Domain ▼        Payment/Refund ▼      Reconciliation   ║
║        (adapter)           (settles money)      (exception layer) ║
║                             ▼                                     ║
║                  Domain Events / Outbox (same tx)                 ║
╚═══════════════════════════════════════════════════════════════════╝
              │                    │                     │
              ▼                    ▼                     ▼
        Analytics/Search    Notifications/Integrations   Data Layer
        (event-fed only)    (event-fed only)             PostgreSQL/Supabase
                                                         ledgers · RLS · outbox
```

## 2. The dependency rule (§178, binding)

```
UI                → Application APIs → Domain Services → Repositories/DB
Agent             → Capabilities     → Application APIs
Analytics         ← Domain Events (outbox)  — never a transaction join
Integrations      ← Domain Events (outbox)  — never a transaction join
```

Forbidden, without exception:

- Any caller outside `app/modules/{catalog,inventory,orders,...}` writing
  `InventoryBalance`, `InventoryMovement`, `Order.status/process_state`,
  `OrderPayment.status`, or any ledger row directly.
- Any agent tool path that reaches the database instead of a Capability →
  Application API call (§132 / ADR-018 already bind tool arguments; this
  closes the write side too).
- Analytics or dashboard aggregates stored inside transaction tables as
  "source of truth" columns (`sales_count`, `revenue_today`, …).

## 3. The bounded domains, mapped to the code

### 3.1 Catalog — source of truth for what is sellable

| Entity (v1.0) | Status today | Where |
|---|---|---|
| Product | ✅ | `catalog/models.py:57` (`products`) |
| ProductOption / OptionValue (relational) | ✅ | `catalog/models.py` (`product_options`, `product_option_values`, `product_variant_option_values`; migration `fd2026100403` backfilled the JSONB) — the variant JSONB is the read model, written by the same service call |
| ProductVariant — **the sellable unit** | ✅ | `catalog/models.py:99` (`product_variants`); inventory and order items already key on `variant_id` |
| SKU | ✅ | nullable, tenant-unique (`catalog/models.py:107`) |
| Identifier (GTIN/EAN/UPC/barcode/QR token/external id) | ✅ | `product_identifiers` (migration `fd2026100402`); resolver `CatalogService.resolve_identifier`; routes `POST /variants/{id}/identifiers`, `GET /identifiers/{type}/{value}` |
| ProductPrice (append-only ladder) | ✅ | `catalog/models.py:131` (`product_prices`), tier ladder via `CatalogService.price_for` (`catalog/service.py:496`) |
| PriceSnapshot at purchase | ✅ (as frozen line) | `OrderItem.title/sku/unit_price` (`orders/models.py:70`) — the order line is the snapshot; no separate snapshot table will be added |
| Media with variant binding | ✅ | `product_images.variant_id` (migration `fd2026100404`), same-product validation in `add_image` |
| External feed provenance | ✅ | `SourceOfTruthPolicy` (`catalog/external/source_of_truth.py:56`), `upsert_from_external` (`catalog/service.py:190`) — per §161 / ADR-038 |

**Rule (§179):** the Variant is the only sellable unit. Inventory, order
lines, prices, identifiers and reservations all reference a variant id —
never a product id. Identifiers resolve to exactly one variant per tenant
(unique `(tenant_id, type, value)`); the resolver is the *only* scan-entry
point POS and agents may use.

### 3.2 Inventory — ledger-centric (already the law of the code)

| Entity (v1.0) | Status | Where |
|---|---|---|
| Warehouse / Location | ✅ | `inventory/models.py:38` |
| InventoryBalance (projection) | ✅ | `inventory/models.py:49` — mutable, derived |
| InventoryMovement (append-only ledger) | ✅ | `inventory/models.py:73` — **the source of truth**; closed reason vocabulary; `balance_after` on every row; `ledger_seq` (migration `fd2026100405`) gives the replay a true total order, since `created_at` is transaction time and the uuid4 id is not an order |
| Reservation (durable, TTL) | ✅ | `inventory/models.py:125` (§140); states ACTIVE/EXPIRED/CONVERTED/CANCELLED |
| Transfer | ✅ | `inventory/models.py:108`, paired `transfer_out`/`transfer_in` rows |
| Ledger↔balance reconciliation job | ✅ | `InventoryReconciliationService.reconcile_tenant` (`inventory/reconciliation.py`): chain check (LAG replay) + projection check + orphan check → `inventory_reconciliation_findings` rows; `reconcile_inventory` runs half-hourly from `RECURRING_JOBS` |

**The flow (§181), already enforced in `InventoryService.move`
(`inventory/service.py:191`):**

```
Command → Inventory Service → lock balance (SELECT … FOR UPDATE, :690)
        → validate preconditions (available = on_hand − reserved ≥ qty)
        → append Movement (single writer, :254)
        → update projection in the same transaction
        → commit (caller owns it)
```

`UPDATE stock = stock − 1` is illegal — the ledger row is the mutation. The
invariant `on_hand == Σ signed physical movements` and the settlement check
(`check_physical_settlement`, `inventory/service.py:126`) are binding.

### 3.3 Commerce — the canonical transaction engine

| Entity (v1.0) | Status | Where |
|---|---|---|
| Order (channel-agnostic) | ✅ | `orders/models.py:30`; `channel` vocabulary at `:54` |
| OrderItem (frozen line snapshot) | ✅ | `orders/models.py:70` |
| Payment | ✅ | `orders/models.py:138` — §141 vocabulary incl. UNKNOWN |
| Refund (ledger row, derived state) | ✅ | `orders/models.py:166` + `orders/money.py:refund_state` (ADR-054) |
| Fulfillment | ✅ | `Shipment` (`orders/models.py:116`) — this is the v1.0 "Fulfillment" entity |
| Order status machine | ✅ | `orders/service.py:53` (`TRANSITIONS`) + append-only history `:95` |
| Order process saga (§139) | ✅ | `orders/service.py:114` (`_PROCESS_TRANSITIONS`), engine `core/saga.py` |
| Payment state machine | ✅ | §141 vocabulary; monotone guard `money.reconciliation_refusal` (`orders/money.py:253`) |

**Rule (§185):** the order does not care where it came from. WhatsApp,
Instagram, website, POS, API and the Agent all produce the same
`CreateOrder` command; the source is only `Order.channel`. Every channel
then rides the identical commerce lifecycle.

### 3.4 POS — an adapter, not a sales source (§189; backend v1 built)

POS is a bounded adapter over the Core, never a parallel engine (`app/modules/pos`):

```
Scanner → Identifier Resolver (§179) → Variant → Cart
        → CreateOrder (channel="pos", register's warehouse) → Payment capture
        → inventory settlement (reservation convert, §140)
        → cash row (method=cash) + Receipt
```

POS vocabulary (Register, Session, CashMovement, Receipt) is POS-domain state
(`fd2026100406`; one OPEN session per register via partial unique index); it
issues commerce/inventory *commands* and never writes balances, movements or
order state directly. The manual cash route refuses `cash_sale`/`cash_refund`
on the wire — those rows are written only by the sell flow, the same
discipline as the inventory `hold`/`release` rows. POS refunds stay on the
orders refund path (ADR-054).

### 3.5 Payment layer & reconciliation

- Payment/Refund live inside Commerce (§3.3) behind the provider-agnostic
  port; UNKNOWN is reconciled by provider lookup, never auto-retried
  (§141). Existing: `OrderService.reconcile_payment`
  (`orders/service.py:903`), stuck-payment sweep (`:980`, scheduler-wired).
- **Reconciliation layer (§188) becomes a first-class quadrant:**

| Reconciliation | Compares | Status |
|---|---|---|
| Inventory | `InventoryMovement` ledger ≟ `InventoryBalance` projection | ✅ (`reconcile_inventory` sweep → findings rows, §188) |
| Payments | orders ≟ payments ≟ captured amounts | ✅ partial (`reconcile_payment`, `money.order_balance`) |
| POS cash | session ≟ expected cash ≟ actual cash | ✅ (`PosService.close_session`: expected computed from rows, variance stored, `pos.session.closed` published) |
| Cross-domain | reservations ≟ holds in ledger | ✅ (`_pair_release_with_reservation`, `inventory/service.py:403`) |

**Rule: a discrepancy becomes an explicit exception/finding row — never a
silent correction.** The only self-healing allowed is the already-ordered
UNKNOWN→failed sweep with its own audit trail.

## 4. Transaction boundary (§186, binding)

```
Command → Application layer (router/worker/capability)
        → Domain Service (flush-only; caller owns the transaction)
        → Policy · Preconditions · Idempotency
        → one DB transaction: ledger mutation + state transition + outbox
        → commit
```

There is **no side path** that mutates inventory, payment or order state.
Conventions that already make this real:

- Services are flush-only across all three domains (audited 2026-10-04:
  zero `.commit()` in `catalog`, `inventory`, `orders` services).
- Outbox events are written inside the same transaction as the change
  (`add_outbox_event`, e.g. `orders/service.py:568`).
- Lock ordering: order row before payment rows (`orders/service.py:212`);
  balance row locked before any movement append (`inventory/service.py:690`).
- Money is `Numeric(14,2)` Decimal end-to-end (`core/model_kit.py:24`,
  `orders/money.py`) — never float.

## 5. State machines (§183/§184, binding)

No service may write `status = "completed"` by hand. Every sensitive state
belongs to a machine whose transitions are validated in exactly one place,
and every transition leaves an append-only history row.

| Machine | States (closed vocabulary) | Enforced at |
|---|---|---|
| Order.status | draft/pending/confirmed/processing/shipped/delivered/completed/cancelled/refunded | `orders/service.py:53`, history `:653` |
| Order.process_state (§139 saga) | created/paid/stock_reserved/fulfilled/cancelled/returned | `orders/service.py:114` |
| Shipment | pending/picked_up/in_transit/delivered/returned/failed | `orders/service.py:132` |
| Reservation | ACTIVE → CONVERTED \| RELEASED \| EXPIRED \| CANCELLED | `inventory/models.py:125` + `InventoryReservationService` |
| Payment | pending/authorized/captured/failed/unknown/refunded/partially_refunded | §141; monotone rule `money.py:253` |
| POS Session | OPEN → CLOSED, variance recorded at close | `PosService.close_session` |

The dict-per-module pattern was duplicated across 6+ modules (gap CC5).
`core/transitions.py` (`require_transition`) is the shared guard; the orders
domain's three machines (status, shipment, saga) guard through it with
byte-identical error messages. The four legacy sites (automation,
conversations/templates, decisions, identity) deliberately keep their richer,
test-pinned contracts — allowed-state hints or structured `details` — and new
machines (POS included) standardise on the helper.

## 6. Idempotency (§187) — exactly-once effects

Three layers, each with its own key, all already present:

1. **HTTP commands** — `IdempotencyMiddleware` over `idempotency_keys`
   (`core/idempotency.py`), `/api/v1/orders` allow-listed; body-hash conflict
   → 409; fail-closed on store outage.
2. **Event consumers** — inbox claimed *before* the effect via transaction-
   scoped advisory lock (ADR-058); marker and effect commit together.
3. **Provider callbacks / effects** — deterministic effect keys with
   reconciliation (`effects/service.py:222`); payment retries carry stable
   idempotency keys.

New commerce mutations must declare which layer owns their exactly-once
guarantee in the service docstring — silent dedupe assumptions are a review
blocker.

## 7. Security boundary (§178 + §132/§141)

```
Request → Authenticate principal → Resolve tenant (tenant_ctx)
        → Resolve workspace/location scope → Authorize capability
        → Domain command → one DB transaction → RLS + constraints
```

Never `endpoint → query database` directly. Tenant isolation is enforced
twice (app authz + RLS via `app.tenant_id`); the boot reconciler refuses to
start if any tenant table lacks RLS (`core/boot.py`). Every new commerce
table ships with `tenant_isolation` RLS + `sales_app` grants in the same
migration (pattern: `a1b2c3d4e5f6_customer_agent_vision_tables.py`).

## 8. Analytics stays out of the core (§190)

The Core emits; analytics consumes. Outbox → event processor → metrics
(`analytics` module reads via its own read models today — dashboard,
drivers, findings). No analytics column will be added to `orders`,
`inventory_balances`, `product_variants` or any ledger table. Derived
"growth" numbers (`net_collected`, `order_balance`, `lifetime_value`) live
in `orders/money.py` as pure functions over core rows, and remain the only
approved way to compute them.

## 9. Adoption plan (dependency order, no scope cuts)

| Phase | Content | Status |
|---|---|---|
| P0 | Adopt v1.0: this doc + §178–§190 + ADR-061 + gap register | ✅ done |
| P1 | Catalog identifiers: table + resolver + routes + tests (unlocks POS) | ✅ done (`fd2026100402`) |
| P2 | Relational options/option values (CC2) with JSONB backfill migration | ✅ done (`fd2026100403`) |
| P3 | Media variant binding (CC3) | ✅ done (`fd2026100404`) |
| P4 | Inventory reconciliation job: ledger ≟ balance as explicit findings (CC4) | ✅ done (`fd2026100405` + `reconcile_inventory` sweep) |
| P5 | Shared transition-guard engine (CC5) | ✅ done as a decision — `core/transitions.py` is the standard; orders' three machines migrated byte-identically; the 4 legacy sites keep their richer, test-pinned contracts by design |
| P6 | POS adapter domain: register/session/cash/receipt | ✅ done backend v1 (`fd2026100406`) |
| P7 | POS cash reconciliation (completes the quadrant) | ✅ done — session close stores the variance, publishes `pos.session.closed` |

## 10. Non-goals (unchanged by v1.0)

- Supabase Auth migration (`docs/SUPABASE_RUNTIME.md` keeps one identity
  authority until a full design exists).
- Moving the event bus into Postgres (PGMQ) — Redis Streams stays transport.
- Multi-currency per tenant — §47/ADR-053 stands: one currency, mismatch is
  a refusal.
- Editing any applied migration — new revisions only, current head
  `fd2026100401`.
