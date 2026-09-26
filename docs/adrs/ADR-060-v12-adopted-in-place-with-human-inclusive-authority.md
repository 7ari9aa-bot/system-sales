# ADR-060 — V12 is adopted in place: the authority chain covers human actors too, payments stay provider-agnostic, and the three-phase program replaces the §42 restructure

- **Status:** Accepted — owner decisions recorded 2026-09-26.
- **Date:** 2026-09-26
- **Spec:** SALES OS V12 (62 locked invariants, §1–§45), evaluated against `docs/SYSTEM_BASELINE.md`
- **Related:** §13–§16 and §132–§136 (AI governance, the chain's ancestors), §135 (approvals), §17 (version predicates), §152 (event log), §174/§177 (ADR discipline, non-negotiables)

## Context

The owner adopted the V12 architecture (authority-centered agentic commerce OS) as the
development program's specification. Measured against the baseline, 27 of the 62
invariants are already held by code, 11 partially, and the 24 missing cluster into one
coherent block: the Decision → Capability → Authority Lease → Atomic Execution chain,
the Evidence Platform, the Effect Ledger, the Financial Ledger, and Claim Safety.

Four questions could not be answered by measurement and needed the owner. The owner
answered them on 2026-09-26.

## Decisions

1. **No §42 restructure.** The new machinery lands inside the existing
   `backend/app/modules/` layout (new modules: `decisions`, `evidence`, `authority`,
   `effects`, `financial` — final names at implementation). The dependency direction
   V12 §42 locks is already enforced by `tests/test_module_boundaries.py`'s ratchet
   over the same layout. Rationale: the ratchet, not the directory tree, is what holds
   the boundary; a ~60k-line move buys shape, not guarantees, and freezes development
   for its duration.
2. **The chain covers human actors too.** Every sensitive mutation — human, AI,
   automation — mints a Decision and consumes an Authority Lease; invariant 27
   ("execution-time authorization") is actor-independent. The owner explicitly chose
   the heavier scope. Enforcement stays risk-tiered so the chain's weight lands where
   the risk is: LOW-risk human actions mint their decision+lease server-side inside
   the same transaction (invisible to the click, no extra UI step), MEDIUM surfaces
   the decision, HIGH/CRITICAL require the durable approval the human path already
   has (§135). The AI path always takes the full explicit chain.
3. **Payments are provider-agnostic until the owner names one.** `PaymentPort`
   (authorize/capture/cancel/refund/get_status) is built against a deterministic
   fake/sandbox adapter; Moyasar/Paymob/Stripe are adapters behind the same port, and
   the Financial Ledger posts from the ledger, never from a provider SDK. The owner
   picks the provider before Wave C's real-provider adapter; nothing in the design
   depends on which.
4. **No table renames.** V12's canonical names map onto existing ones
   (`order_items` ≈ order_lines, `order_payments` ≈ payments, `workflow_executions`
   ≈ workflow_instances...); new tables are added, existing names stay — the 58
   applied migrations are immutable and the expand/contract discipline stays.

## Consequences

- New modules under `app/modules/` own the new truths; no existing module's repository
  is imported across its boundary (the ratchet holds).
- `event_log` gains `decision_id` / `effect_id` columns (expand migration) so §56's
  lineage is reconstructable from the durable log.
- Human UX cost is real and accepted: HIGH/CRITICAL staff actions keep (and formalize)
  the approval step; LOW/MEDIUM actions gain server-side minting with no added clicks.
  The Decision/Evidence/Lineage UI surfaces (V12 §4) are how staff sees what minted.
- The three-phase program (web 100% → desktop product → website builder) is recorded
  in `docs/PLAN_V12_PROGRAM.md`; each phase closes green on `main`.
- Production Supabase migration application happens per explicit owner approval,
  step-verified, regardless of Wave 0 scheduling.
- Spec mapping duty: the V12 invariants are cross-referenced to the §1–§177 matrix
  rows they sharpen; where V12 supersedes an old section's letter (e.g. §135's
  approval binding gains the hashes), the ADR records the delta — the matrix rows are
  updated in the wave that closes them.
