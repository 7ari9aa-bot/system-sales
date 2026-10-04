# ADR-061 — The Commerce Core is a bounded domain the platform depends on, not the reverse

- **Status:** Accepted
- **Date:** 2026-10-04
- **Spec:** §178–§190 (`docs/spec/ARCHITECTURE_PATCH_178-200.txt`)
- **Related:** ADR-028 (canonical entity model), ADR-038 (external commerce), ADR-022 (sagas), ADR-051/052 (order + return sagas), ADR-054 (refund ledger row), ADR-060 (V12 in place); narrative `docs/COMMERCE_CORE_ARCHITECTURE.md`

## Context

The owner directed that commerce be formalized as an independent Core Domain
(v1.0) — Catalog / Inventory / Commerce behind one transactional boundary, with
POS as an adapter and analytics strictly event-fed — *before* any further
reshaping of the Supabase schema and code.

A code audit on 2026-10-04 (all `file:line` in the narrative doc) shows most of
the demanded machinery already exists and is uniformly applied: the append-only
`InventoryMovement` ledger with locked-balance mutation flow
(`inventory/service.py:191,254,690`), durable §140 reservations with the
settlement refusal, both order state machines with history rows
(`orders/service.py:53,114`), §141 payment vocabulary with the monotone
reconciliation guard (`orders/money.py:253`), transactional outbox emission
(`orders/service.py:568`), flush-only services across all three modules, and the
three-layer idempotency stack.

The real deltas are: no product identifiers (blocks any POS scanning flow), JSONB
options instead of relational ones, media without variant binding, no runtime
ledger↔balance reconciliation job, six duplicated dict state machines with no
shared guard, and zero POS presence in spec or code.

## Decisions

### 1. Adopt Commerce Core v1.0 as a bounded domain

The dependency rule is binding: UI → Application APIs → Domain Services → DB;
Agent → Capabilities → Application APIs; Analytics/Integrations ← Domain Events
only. Nothing external touches the ledger, balances or order state.

### 2. The ledger and the machines stay exactly where they are

The existing inventory ledger, reservation lifecycle, order/process/shipment/
payment machines and money discipline are adopted *as the* v1.0 semantics — this
document re-states them as spec §181–§184 rather than redesigning them.

### 3. Catalog identifiers are the next schema addition

`product_identifiers` (tenant, variant, closed type vocabulary, unique
`(tenant_id, type, value)`) plus a resolver service and routes. POS (§189) is
gated on this slice; its scanning flow begins at the resolver.

### 4. Reconciliation becomes a first-class quadrant

Inventory ledger≈balance, payments, POS cash (future), reservation/hold pairing.
Discrepancies are explicit findings, never silent corrections (§188).

### 5. One shared transition-guard helper, no behaviour change

The duplicated dict machines (gap CC5) converge on one `core/` helper in a later
wave; vocabularies and histories are untouched until then.

## Rejected

1. **Big-bang schema rewrite of Supabase before adoption** — the audit shows the
   core semantics are already in the code; a rewrite would discard enforced,
   tested behaviour for a diagram.
2. **POS as a separate service/database** — it is an adapter domain inside the
   same transactional truth (§189); a separate write path would break exactly-once
   settlement.
3. **Analytics columns in transaction tables** — breaks §190 and re-couples the
   read plane to write latency.
4. **Renaming/re-numbering existing ADRs or spec sections to "fit" v1.0** — the
   two-namespace ADR rule and §n stability win (ADRS.md §5).

## Consequences

- New commerce tables ship with RLS + `sales_app` grants in their own migration
  (head `fd2026100401` → new revisions only).
- Phases P1–P7 in the narrative doc are the execution order; P1 (identifiers)
  lands first, P6 (POS) waits for it.
- The gap register carries the six deltas (CC1–CC6) with evidence until each is
  closed.
- Reviews of commerce PRs now check §178–§190 conformance (dependency rule, flush
  only, outbox-in-tx, declared idempotency layer).
