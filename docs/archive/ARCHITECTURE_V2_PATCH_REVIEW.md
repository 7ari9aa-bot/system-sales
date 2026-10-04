# Architecture Patch Review (§125–§177) — Adoption Decision

Verdict: **ADOPT — with 3 scoped deferrals.** The patch is the strongest
document in the series: it closes real holes that exist in the RUNNING build
today, not hypothetical ones. Evidence below.

## What it catches in our live build (verified, not theoretical)

1. **§126 Conversation serialization — real race, live today.** Our AI
   auto-reply (hooks.maybe_auto_reply) has NO lease: two messages arriving
   within seconds can spawn two parallel AI runs writing to the same
   conversation. Must fix in Wave 2 (lease + ownership state + stale-run
   cancellation).
2. **§127 Consumer idempotency — we claim idempotency, we don't enforce it.**
   Worker retry path can double-apply effects (outbox republish + crash
   between ack). ProcessedEvent inbox table with unique (consumer_name,
   event_id) in the SAME transaction as the effect.
3. **§152 Outbox vs EventLog — we never clean outbox_events.** It is silently
   becoming our permanent log with status columns. Split: durable EventLog
   (append-only) + outbox as disposable buffer with cleanup after publication.
4. **§129 Outbound UNKNOWN state** — our delivery marks failed on any
   exception; a timeout after provider acceptance would be wrongly retried →
   duplicate messages. UNKNOWN + reconciliation is required before production
   WhatsApp.
5. **§132 Tool scope binding** — our tools are tenant-scoped (RLS) but not
   conversation/customer-scoped. `get_order(any_id)` inside tenant is
   allowed today. Server-side scope binding per conversation needed in W3.
6. **§140 Inventory Reservation as durable entity** — we keep a `reserved`
   counter with no rows, no expiry, no conversion. Abandoned carts leak
   reserved stock forever. Reservation table with expires_at in W2.

## The 3 deferrals (with reasons — not avoidance)

| Item | Decision | Why |
|---|---|---|
| §151 Workspace/Location retrofit | Adopt hierarchy in NEW tables (workspaces, locations, channel_accounts, inventory); existing 60+ tables stay tenant-scoped. Retrofit via expand-contract when multi-location becomes a real requirement (ADR-005) | Adding two columns to every table now costs weeks and serves zero current users; the ownership decision is documented so the migration is mechanical later |
| §142 UUIDv7 | Defer to partitioning wave | PK generation change = churn across FKs for a benefit that matters at partition scale; PG18 ships native uuidv7 |
| §169 Evaluation pipeline depth + §168 SLO numbers | Build the FRAMEWORK now (tables, statuses, alert hooks), defer depth | No production traffic yet — thresholds need baseline; schema + hooks cost little |

## Adoption mapping into our waves (revised)

- **W1 (running)** — stays. Integration adds: ProcessedEvent table (§127),
  outbox lease columns (§128), EventLog table (§152), retry classes (§64).
- **W1.5 (new, after W1)** — Conversation serialization: lease + fencing,
  ownership states (AI_ACTIVE/HUMAN_ACTIVE/PAUSED/HANDOVER_PENDING/CLOSED),
  stale-run cancellation, outbound UNKNOWN + reconciliation worker,
  durable Reservation entity (§126/129/130/140).
- **W2** — + ChannelAccount lifecycle states (§145), canonical message
  content model (§155), conversation lifecycle (§156), tombstones (§143).
- **W3** — + AI untrusted-input boundary + tool scope binding (§132),
  run limits (§134), durable Approval workflow (§135), knowledge visibility
  (§157), memory governance (§158).
- **W4** — + ScheduledJob durable scheduler (§154), tenant fairness budgets
  (§144), break-glass (§147).
- **W5** — + realtime recovery cursors (§149), notification dedupe/digest
  (§166).
- **W6** — + EventLog consumers, metric registry (§167), SLO framework
  (§168), public customer plane (§159), platform admin plane (§160),
  entitlement centralization (§165), tenant-scoped restore (§164), deletion
  propagation (§172).
- **Deferred to Phase 9**: voice, external commerce connectors, multi-region.

## New ADRs adopted (numbered per §174 index)

ADR-013..045 accepted as the decision catalog. Our local additions:
- **ADR-005** (local): workspace/location hierarchy — model now, retrofit
  later via expand-contract.
- **ADR-006** (local): conversation lease implementation = Postgres advisory
  lock on conversation_id + lease row with expires_at (no Redis dependency
  for correctness).
- **ADR-007** (local): EventLog write happens in the SAME transaction as
  outbox insert; outbox cleanup job only deletes published rows older than
  the EventLog retention guarantee.

## Pre-production gate (§176)

Adopted as the release checklist for the production-hardening wave — all 23
scenarios become automated tests in `tests/gate/`. Nothing ships to a real
tenant until the gate is green.
