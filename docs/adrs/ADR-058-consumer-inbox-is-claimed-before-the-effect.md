# ADR-058 — The consumer inbox is claimed before the effect, not checked beside it

Date: 2026-09-24. Wave 5 / worker reliability.
Evidence: `backend/app/workers/base.py` (`_process_event`, `_claim_inbox`,
`_close_inbox`, `_run_with_lineage`), `backend/app/core/lease.py`,
`backend/tests/gate/test_gate_inbox_dedupe.py` (8: 4 run anywhere, 4 need a
database), `backend/migrations/versions/8a1f6fb95fc6_*.py` (`processed_events`).

## Context

§127 gave every `StreamWorker` a consumer-inbox dedupe: SELECT the
`processed_events` marker, skip if present, else run `handle()` and INSERT the
marker afterwards (marker-after-effect on purpose — a pre-written marker turned
any transient failure into a permanently lost event). That ordering made the
dedupe a **read-then-act**: two workers holding the same stream entry at the
same instant — a sequential redelivery is fine, a *concurrent* one is not —
both read "not processed" and both produce the effect.

Commit `05f07c1` stopped the outbox relay from *manufacturing* such duplicates,
but a Redis-side one stays reachable: `XAUTOCLAIM`/PEL reclaim hands a live
worker's entry to a second worker the moment its idle time crosses the reclaim
threshold, while the first handler is still running. Nothing in the worker loop
made the two racers exclude each other. The invariant to pin is: **for one
event id, at most one worker runs the effect.**

## Decisions

### 1. The claim is a transaction-scoped advisory lock (shape (b))

`_claim_inbox` opens one transaction that: (i) takes
`pg_try_advisory_xact_lock(key)`, keyed on the **pair** (consumer_name,
event_id) by `_inbox_lock_key` — SHA-256 folded into the signed-bigint space,
the same shape as `lease.py`'s conversation lease; (ii) checks the
`processed_events` marker *inside* the lock; (iii) stays open across
`handle()`; and (iv) ends in `_close_inbox`, which INSERTs the marker inside
the same transaction so the COMMIT that persists "done" is the COMMIT that
releases the lock. Between check and effect there is no longer a window: a
concurrent claimer either fails the try-lock (contended) or, arriving after
the winner's commit, sees the marker under its own lock — Postgres' default
READ COMMITTED makes the winner's row visible to the loser's first statement.

Outcomes:

* **contested** — stand down WITHOUT acking. The entry stays in the contended
  worker's PEL; the next reclaim either finds the lock free (the winner
  crashed: claim it, run it) or the marker committed (ack and drain). The
  winner owns the ack of the entry it is actually running.
* **seen** — ack and skip, as before.
* **inbox unreachable** — fail open with no claim, the pre-existing policy:
  a broken dedupe table must not stop the pool, and `message_worker` (which
  sets `_skip_generic_idempotency`) never consults the generic inbox anyway.

### 2. A claim never outlives its effect

Deferred / failed / dead-lettered paths end the claim transaction with no
marker — the rollback releases the lock, so the staged retry (or a PEL
reclaim) can claim the event again. This preserves §127's anti-loss property
that marker-after-effect existed to protect; nothing about the retry, DLQ or
lineage-context behavior changed (`_run_with_lineage` is the old body, moved).

### 3. What a crash between claim and effect costs

A worker that takes the claim and dies before `handle()` completes rolls its
claim back with the process — **the event is not lost**; the reclaim path runs
it fresh. A worker that finishes the effect but dies before the commit replays
`handle()` on redelivery, exactly the exposure the old design had: at-most-one
*concurrent* effect is new; at-most-once *ever* still rests on the handlers'
own status guards. Chosen deliberately over shape (a)'s alternative failure
(losing events), and stated so no reader mistakes the remaining replay window
for a regression.

## Rejected

1. **Shape (a): insert the marker before the effect, treat unique-violation as
   "owned", delete it on failure.** The delete is the flaw: a *crash* between
   claim and effect cannot delete, and the committed marker then suppresses
   every future redelivery — a permanently lost event with no window and no
   retry, a strict regression against §127's marker-after-effect ordering.
   Fencing stale claims would need a second status column plus a lease clock,
   i.e. re-inventing what an xact-scoped lock gets for free: the claim dying
   with its holder. It also breaks `test_pure_failed_effect_leaves_no_claim` /
   `test_gate_failed_effect_leaves_no_marker_to_poison_the_retry` by design.
2. **A blocking `pg_advisory_xact_lock` with a statement timeout.** The
   contended worker would burn the handler's full duration waiting, then see
   the marker — correct but slower than standing down, and the PEL reclaim
   already provides the "come back later" path. Blocking is what `lease.py`
   offers as `wait=True` for interactive callers; the worker loop is not
   interactive.
3. **A `SELECT … FOR UPDATE`-style row claim (INSERT placeholder + lock).**
   Adds claim-state bookkeeping (who owns the row, when is it stale) the
   advisory lock answers without schema. No migration, no new column.
4. **Relying on `outbox_id` stability plus the 05f07c1 relay fix.** That
   removed the producer-side duplicate; it cannot remove a Redis-side reclaim
   race, and handlers are not all idempotent enough to absorb one (that is the
   entire premise of §127).

## Consequences

- `processed_events` keeps its exact schema; the unique constraint
  `(consumer_name, event_id)` is now belt (last-line) not braces (mechanism).
- One extra open transaction per in-flight event per pool. Advisory locks are
  cheap and die with the connection; nothing new to clean up after a crash.
- `test_gate_inbox_dedupe.py` skips its four DB-gated races without an
  application database (this checkout has none) — CI is the venue that
  publishes their verdict. The mutation ("remove the exclusive claim and the
  concurrency test fails") is *demonstrable locally* against the modelled-inbox
  tests and was run: with the try-lock removed, `test_pure_concurrent_workers_
  run_the_effect_once` fails with `the effect ran 3 times for one event id`.
- `message_worker` deliberately stays out: its per-delivery-phase dedupe is
  finer-grained and owns its marker transaction; the generic claim would be
  redundant there, and changing it is a different row's scope.
