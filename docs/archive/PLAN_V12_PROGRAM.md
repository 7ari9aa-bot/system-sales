# PLAN V12 PROGRAM — three owner-defined phases

Adopted 2026-09-26 (owner decisions in `docs/adrs/ADR-060-*.md`). The comparison anchor
is `docs/SYSTEM_BASELINE.md`: every work item is classified
**NEW / COMPLETE-PARTIAL / FIX / ALREADY-DONE** against it before scheduling — items
that turn out ALREADY-DONE are answered with evidence, not rebuilt.

Everything runs on `main` (branch per task, merged within the task's life). Each wave
closes with: a red-then-green test per fix/feature, CI green as `sales_app`, and one
line in `docs/ROADMAP_TO_90.md` §8's progress log.

---

## Phase 1 — the web system, 100% (GIANT)

### Wave 0 — remediation before expansion

| Item | Class | Source |
|---|---|---|
| SEC-1.1 `switch-tenant` tenant_id leaves the query string + a graph-wide "tenant is never a query parameter" guard | FIX | ROADMAP §9 |
| SEC-1.2 realtime `?token=` narrowed to a short-lived stream-scoped credential | FIX | ROADMAP §9 / ADR-059 R5 |
| SEC-1.3 voice tables get the canonical tenant-isolation policy sweep | FIX | ROADMAP §9 |
| OPS-1 `/metrics` worker counters get their writers | FIX | GAP_REGISTER |
| OPS-1 `check:search-hits` wired into npm scripts + CI (F7 gate) | FIX | GAP_REGISTER |
| `/operations` page stops bypassing `api()` (auth header + `/api/v1` prefix) | FIX | baseline §2 |
| Worker engine pool sized from config with the ≥2×(pools+1)+headroom invariant pinned by a test | FIX | GAP_REGISTER capacity note |
| Production Supabase: apply the 25 pending revisions — ONLY on explicit owner approval, step-verified | OWNER | ROADMAP §9 |

### Wave A — Evidence + Decision (the correctness substrate)

- NEW `app/modules/evidence/`: `evidence_facts`, `evidence_sets` (§9 of V12: hashes,
  freshness, provenance, trust levels; repeated single-source claims ≠ confirmation).
- NEW `app/modules/decisions/`: `decisions` + `decision_dependencies` (state machine
  PROPOSED→VERIFIED→…→EXECUTED/STALE; TTL; resource_versions JSONB).
- Risk engine service (LOW/MEDIUM/HIGH/CRITICAL, dynamic escalation inputs) — generalizes
  §15's tool risk levels; shared by every actor.
- Boot Reconciler: startup FATAL unless RLS ENABLE+FORCE+policy verified per tenant table
  (invariant 13) — extends the fail-closed config discipline.
- Correctness SLOs into `/metrics` (invariant 62): decision_stale_rate, authority
  rejection, version_conflict, budget_fail.
- `event_log` expand migration: `decision_id`, `effect_id` columns.

### Wave B — Capability + Authority Lease + the Atomic Execution boundary

- NEW `app/modules/authority/`: `capability_grants`, `authority_leases` (V12 §20–§22:
  nonce, single-use, command_hash, expected_versions, 60s TTL, revocation).
- `core/commands.py`: canonical_json + command_hash (deterministic, tenant-pinned).
- The Atomic Execution boundary service (V12 §23's 15 steps, one transaction): verify
  chain → reserve budget → redeem capability → versioned domain mutation → effect
  intent → outbox → lineage → COMMIT. External dispatch AFTER commit.
- Budget hierarchy generalized from the AI reserve/settle (§42): `autonomy_budgets` +
  `budget_reservations` with parent-sliced reservations (V12 §25).
- Actor coverage per ADR-060: humans too; LOW mints server-side invisibly, MEDIUM
  surfaces, HIGH/CRITICAL ride the existing durable approval (§135) now bound to
  command_hash + evidence hashes.
- First proven end-to-end case: the AI `create_order` tool executes through the full
  chain (its §132 server-side scoping becomes lease scoping).

### Wave C — Effects + Money

- NEW `app/modules/effects/`: `effect_ledger` (V12 §30: deterministic idempotency key
  H(tenant+operation+args+workflow+task), AMBIGUOUS state, provider_reference,
  reconciliation) + post-commit dispatcher + reconcile worker paths (generalizes the
  message/payment reconciliation that already exists).
- NEW `app/modules/financial/`: chart of accounts, `financial_transactions`,
  `financial_entries`, posting rules for payment/refund/partial-refund/chargeback/COD/
  fees/tax/discount; invariant `SUM(debits)==SUM(credits)` enforced by a constraint and
  a gate test (V12 §31).
- `PaymentPort` + deterministic sandbox adapter (ADR-060 decision 3); Moyasar/Paymob/
  Stripe adapters wait for the owner's provider choice.
- Money-in-motion rules ride §47 (tenant currency, minor units at the provider edge).

### Wave D — Claim Safety + coverage completion

- `claim_checks` gate inside the guardrail chain (V12 §26): generated commercial claims
  verified against authoritative evidence with freshness; no evidence → BLOCK.
- Memory admission upgrade to the V12 trust/admission state machine (§158's provenance
  columns already exist; add the formal states).
- Composite FK sweep `(tenant_id, id)` where a child references a tenant-owned parent
  (invariant 14) — expand-only migration.
- Approvals (§135) re-bound to command_hash + evidence_set_hash + dependency hash.

### Wave E — the surfaces that make V12 visible (frontend)

- Decision View, Evidence View, Execution Lineage, Audit Explorer, Reconciliation
  Console (V12 §4) — new pages under `(dash)`.
- Complete the partial surfaces: my-work writes, AI page depth, palette search to all
  entity types, saved views across lists, `/operations` parity.
- Thin pages become real (typed, tested): journeys, leads, live, sla, queues,
  integrations, team.
- Phase-1 test bar: every user flow has a Playwright case; scripted user journeys
  (UAT) run against a staging deployment; the backend suite + gate scenarios stay
  green as `sales_app`.

**Phase 1 = 100% when:** the checklist above is closed with evidence, the V12 core
chain is exercised end-to-end by both an AI actor and a human actor on a real flow
(checkout), and the compliance matrix rows touched by it are re-measured.

---

## Phase 2 — the desktop product (GIANT)

Phase-0 scaffold is green; product work starts after Phase 1's contract (the lock) is
V12-stable. Codegen reads the lock; Stronghold single-flight refresh; offline reads
never invent authority (V12 §42: offline actions queue and re-authorize on reconnect).
Its own wave breakdown lands as an ADR-drill before code.

## Phase 3 — website builder (GIANT)

`website-builder/` exists at the repo root as a separate surface. Its architecture
(tenant-scoped site definitions, hosting plane, the public customer plane §159) gets
its own ADR set before code. Sequenced after Phase 2 — recorded now so the program is
explicit, not implied.
