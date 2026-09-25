# ROADMAP TO 90% — Sales OS / `system-sales`

Status: **active plan**. Owner decisions needed are in §7.
Baseline measured: **2026-09-20**.

---

## 1. How the percentage is computed (the rubric)

The number is meaningless without the rubric, and I have been burned by that already
(an earlier "~72%" was measured against "a route exists and a page renders it", not against the
spec's Definition of Done).

**This plan uses the audit's rubric**, because it is the stricter and more honest one:

- The architecture's 96 capabilities are each scored **complete = 1, partial = 0.5, missing = 0**.
- A capability is **complete** only when ALL of the following hold:
  1. It is implemented against the spec section it claims to satisfy.
  2. A test exists that **fails before the fix and passes after**.
  3. The test runs on real Postgres in CI (or staging), **not only against production**.
  4. It has been exercised **once for real** — a row exists, a request succeeded, a log line was
     emitted. "It passed CI" is not evidence.
- Anything meeting only (1) is **partial**, however much code it has.

**Where we are:**

| | value |
|---|---|
| capabilities complete | **~11** of 96 |
| partial | ~68 |
| missing | ~17 |
| **weighted coverage** | **~46%** |
| **DoD-complete** | **~11%** |

90% means roughly **86 of 96 complete**. That is ~75 items moving from partial/missing to complete.
It is a multi-wave effort, not one session — anyone who says otherwise is guessing.

---

## 2. The teams

Six workstreams. Each owns **disjoint modules** so parallel agents cannot collide on the same files
(the failure mode that cost real time earlier in this project). One reviewer team is deliberately
outside all of them.

| Team | Owns (files/modules) | Architecture |
|---|---|---|
| **WS1 Domain & Channels** | `conversations/`, `customers/`, `orders/`, `catalog/`, `inventory/`, `marketing/` | §26–36, §81–84 |
| **WS2 AI** | `ai/`, `core/guardrails.py` | §37–44 |
| **WS3 Platform** | `billing/`, `privacy/`, `segments/`, `platform/`, `operations/`, `analytics` | §45–57, §76–84 |
| **WS4 Security & Integrity** | `core/`, `identity/deps.py`, cross-cutting middleware | §10–25, §68–69 |
| **WS5 Frontend** | `frontend/` | §85–113 |
| **WS6 Ops & Environments** | `infra/`, `.github/`, `workers/`, `scripts/` | §58–59, §70–72, §114–117 |
| **REVIEW** | read-only across all of the above | — |

**Orchestrator (me)** routes, tracks state, commits, and runs CI. Agents do **not** run git.

---

## 3. Waves

Ordered by dependency and by the audit's own sequencing. Each wave ends with a review gate.

### Wave A — Integrity foundations (mostly done)
| Item | State |
|---|---|
| G-01 anon/RLS exposure | ✅ closed, verified in production |
| G-02 approval bound to arguments | ✅ closed |
| G-04 worker deployment proof | ⬜ needs WS6 |
| G-05 config fails closed | ✅ closed |
| G-07 browser headers | ✅ closed (token storage still open) |

### Wave B — Make what exists actually work (done)
| Item | Team | State |
|---|---|---|
| N-01 entitlements | WS3 | ✅ closed |
| N-02 tenant suspension (API + auth + workers) | WS4 | ✅ closed |
| N-04 default privileges | WS4 | ✅ closed |
| N-05 provisioning seed + live smoke | WS6 | ✅ closed |
| N-07 AI tool surface + RAG injection | WS2 | ✅ closed |
| G-09 consent enforced at send | WS1 | ✅ closed |
| **Job RUNNER (the executor behind the control surface)** | WS3 | ✅ closed |
| G-13 circuit breaker wired | WS4 | ⬜ **`app/core/circuit_breaker.py` exists and nothing calls it** |

> Re-measured 2026-09-20: the table above said "next / in progress" for four items that the
> progress log already recorded as closed. Corrected against the log rather than the plan.


### Wave C — Breadth to reach the target
| Item | Team | Verified state (2026-09-20) |
|---|---|---|
| G-08 outbox `locked_at` + replay | WS4 | ✅ closed (2026-09-24) — measured first: §152 `event_log` replay and the claim's `FOR UPDATE SKIP LOCKED` were already there, but the claim had **no claim instant**. The stranded-row reclaim measured its lease from `created_at` (when the event was *staged*), and the batch claim committed the whole batch at its first per-row commit — leaving the rows it had not yet published durably `publishing` **and unlocked**, so a second relay reset them to `pending`, re-claimed and re-published them **concurrently**. Consumer dedupe (`meta["outbox_id"]` → `processed_events`) is a read-then-act, so it absorbs a *sequential* redelivery, not a simultaneous one: **double side effects** was the live failure mode, not silent loss. Fixed with **no DDL** — no `locked_at`/`lock_owner` column was needed, because claim → publish → mark now share ONE transaction per row, so the row's Postgres lock *is* the lease and a relay that dies mid-publish rolls its own claim back (row returns to `pending` immediately, never stranded). The §128 reclaim stays as a backstop, now `FOR UPDATE SKIP LOCKED` with both durations from config (`outbox_lease_seconds`, `outbox_failed_requeue_seconds`) instead of a literal `interval '5 minutes'`. Pinned by `tests/test_outbox_claim.py`; the race/lease cases are DB-gated (CI-only, they need `DATABASE_URL_APP_ADMIN`) |
| G-14 `Idempotency-Key` on side-effecting writes | WS4 | ✅ built + tested — **frontend calls it**: every order write (`create`, refund, cancel, return) goes through `apiWithMeta(… { idempotencyKey })`, one key per dialog open, never re-minted after a 409 (`frontend/src/components/orders/order-write-ui.tsx`, `504a985`) |
| G-15 `If-Match`/ETag optimistic concurrency | WS4 | ✅ built + tested — **frontend calls it**: the shipping PATCH carries the version the detail read answered with, and a lost CAS blocks the submit until the merchant re-reads (`shipping-dialog.tsx:119-141`, `504a985`) |
| §25 layered rate limits (tenant/user/endpoint) | WS4 | ✅ closed |
| §33–35 media pipeline + Attachment | WS1 | ✅ closed |
| §32 marketing consent entity | WS1 | ✅ closed |
| §51–52 privacy + retention completion | WS3 | 🟡 retention worker wired to a job type; completeness unverified |
| §53–54 billing metering + immutable snapshots | WS3 | ✅ closed (2026-09-24) — metering landed, and immutability is now a DB rule, not a convention: `uq_invoices_tenant_period` (one snapshot per period) + the `BEFORE UPDATE OR DELETE` row guard `e7a8b9c0d1e2` + the `BEFORE TRUNCATE` guard `a9b0c1d2e3f4` (statement trigger, and `REVOKE TRUNCATE ON invoices` re-asserted by `scripts/provision.py` after its blanket `GRANT ALL`). Pinned by `tests/test_invoice_immutability.py` + `tests/test_snapshot_truncate_freeze.py`; the refusal tests are DB-gated (CI-only, they need `DATABASE_URL_APP_ADMIN`) |
| §55–57 analytics read models, partition-ready, archiving | WS3 | ✅ closed (2026-09-24) — the row was wrong on both counts: `app/modules/analytics/` exists (service, router, retention, timekit, metrics), `ai_usage` is RANGE-partitioned on `period_date` with a DEFAULT catch-all and `core/partitioning` maintains the horizon (`546f109`), a month drops only after a tenant chose a policy through `PUT /analytics/retention/policies/{data_class}` (`cab9795`), and the row stores the worker purges — `messages`, `webhook_events` — are choosable through that same gate rather than a second allowlist (`edd5d46`). The read models answer what `/metrics/definitions` advertises, including `conversion_rate` and `roas` (`f476056`), and §55's "the browser must not aggregate" rule is now enforced on the AI surface too: the period total is summed by `ai/router.py:131` as an exact `Decimal`, not by the page. What genuinely stays open is §57's other half — the per-table question of which personal-data stores have a horizon a tenant can choose and which are keep-forever by legal-audit duty; that audit is `GAP_REGISTER`'s, not this row's, and is listed there |
| §82 segments as a shared entity | WS3 | ✅ closed (2026-09-24) — `modules/segments/` is the single owner (service + router + DSL guard at `tests/gate/test_gate.py:229`), and it finally has a PRODUCER as well as a reader: `scheduler_worker` sweeps `segments.recompute` every 6h and refuses to double up on a run already in flight, so a segment is not a row that goes stale forever after the compute endpoint is called once (`1c006aa`, `tests/test_segments_recurring.py`) |
| §65–67 security events + audit enrichment | WS6 | 🟡 read half closed, export half is external — `GET /security-events` now exists for an operator (`platform/router.py`, `settings:read`, explicit tenant filter, `redact_fields`), and the two write-path defects that made the trail lie are gone: an expired invitation writes its event through the canonical `record_security_event` on its own transaction instead of riding a request transaction that rolls back and loses the row, and `account_disabled_login` carries an email DOMAIN, not the address (`1c006aa`, `tests/test_security_event_write_paths.py`). `docs/COMPLIANCE_MATRIX.md:82` stays 🟡 for the one thing this repo cannot close alone: no OTel collector endpoint is configured, which needs the tenant's observability vendor |
| §114–116 security + performance test suites | WS6 | 🟡 **the two named gaps now exist as tests; the CI verdict is still open.** §114/§115: `tests/security/test_role_authz_matrix.py` drives the real mounted route graph over ASGITransport with `get_tenant_ctx` overridden to each role's *actual* seeded permission set (`ROLE_MATRIX` imported from `scripts/provision.py`, so the matrix cannot drift from what is provisioned), and `tests/security/test_tenant_access_matrix.py` has two layers — a structural one that fails the moment a resource route appears without `get_tenant_ctx`, and a DB-backed one that seeds a real second tenant and asserts not-found/refused/empty for its customers, orders, conversations, list/search, identity merge, CSV import and §151 scope. The structural layer is where `POST /platform/secrets/{provider}/rotate` was found: gated on tenancy only, so any tenant member could rotate the tenant's channel credential. §116: `tests/perf/test_hot_path_budgets.py` puts a wall-clock budget on create-order (300 ms), revenue summary (250 ms) and Customer 360 (150 ms). **What stays 🟡 is honest venue, not missing code:** the DB-backed half of §115 skips locally without `DATABASE_URL_APP_ADMIN`, and the perf budgets have never printed a p50/p95 — CI is the first place either is observed, and a budget nobody has seen pass is a claim, not a gate |
| Playwright E2E in CI; frontend ESLint | WS5 | ✅ closed (26 specs green) |
| Remaining W5 surfaces (Customer 360 done; command palette done) | WS5 | ✅ closed (2026-09-24) — the approvals page is built (`app/(dash)/approvals/page.tsx` + `components/approvals/`), and it reads the queue the way the backend actually answers: `truncated` is surfaced instead of a silent 100-row cap, and deciding is one-shot because the decision is `ValidationError → 400` under row locks (`455e571`, `e2e/approvals.spec.ts`) |

> Only rows I re-measured in the code carry a verdict here. The lesson from Wave C repeats in
> Wave B's G-13: **the failure mode is not "not built", it is "built, tested in isolation, and
> never called".** A unit test on an unused module passes forever and proves nothing.


### Wave D — Requires an owner decision (§7)
G-03 staging · G-06 SecretStorePort · G-17 workspace/location RLS · G-18 money minor units ·
G-07 token storage migration (needs CSRF first)

---

## 4. Definition of Done — the gate every item passes

An item is **complete** only when all four hold. The reviewer team checks this and can reject.

1. **Implemented** against its spec section.
2. **Test that fails before, passes after** — the reviewer verifies this by reverting the fix
   mentally or in a scratch copy; a test written after the fact that would pass on the old code is
   not evidence.
3. **Runs in CI on real Postgres.**
4. **Exercised for real once** — a row, a request, a log line. For anything with a user-visible
   surface, the smoke script (`scripts/smoke_production.py`) gains a check.

---

## 5. Review protocol

Every artifact gets eyes that did not produce it.

| Gate | Who | What they check |
|---|---|---|
| Spec review | Reviewer | Is this the right item? Is the spec section satisfied, or only its shape? |
| Build review | Reviewer | DoD 1–4 above. Adversarial: try to make the new test pass on the OLD code. |
| Integration review | Reviewer | Does it break a boundary (the ratchet in `tests/test_module_boundaries.py`)? Does it break an existing guarantee? |
| Orchestrator | me | CI green, production verified, then commit. |

**Reviewers are instructed to reject, not to be agreeable.** A review that finds nothing is
treated as a weak review, not a clean one.

---

## 6. Standing constraints (from the audit, non-negotiable)

- No new cross-module import cycles. The ratchet fails on one.
- No new feature while a Wave A/B item it depends on is open.
- Never claim an item complete without the DoD evidence.
- Never report a coverage number without stating the rubric.
- Migrations: one statement per `op.execute()`; guarded so plain-Postgres CI can run them.
- Do not touch `tenants`, `users`, `refresh_tokens` RLS assumptions — global tables read before the
  tenant GUC is bound.

---

## 7. Decisions the owner must make (I cannot)

| # | Decision | Why it is yours |
|---|---|---|
| D-1 | **Staging environment** (G-03) | Costs money: a second Railway service + a separate Supabase project. Blocks G-04 and every "prove it works" item that should not run on production. |
| D-2 | **Vault access for the app role** (G-06) | Granting `sales_app` USAGE on `vault` + SELECT on `decrypted_secrets` lets the app decrypt *every* secret. A real broadening of access. |
| D-3 | **Money representation** (G-18) | ADR-001 says keep `Numeric(14,2)`; the audit's gap register says minor units. They contradict. Someone must pick. |
| D-4 | **workspace/location RLS** (G-17) | Needs a product answer: are workspaces a real isolation boundary, or just grouping? |
| D-5 | **Token storage migration** (G-07) | Cross-site cookies need CSRF first; that is a security-posture change, not a refactor. |

---

## 8. Progress log

| Date | Commit | What closed |
|---|---|---|
| 2026-09-20 | `e2fbe3f` | G-01 anon exposure revoked (verified: anon key now 401) |
| 2026-09-20 | `57729d1` | N-02 API + auth enforcement |
| 2026-09-20 | `702d150` | N-02 workers (defer, don't fail) |
| 2026-09-20 | `f4682f5` | SLA closed-weekday read as 24/7 |
| 2026-09-20 | `08afa4b` | N-05 provisioning seed |
| 2026-09-20 | `9691a7a` | G-05 config fails closed |
| 2026-09-20 | `01635fa` | G-07 browser security headers |
| 2026-09-20 | `0b1dbd0` | G-07 access token out of URLs |
| 2026-09-20 | `f597102` | G-02 approval bound to arguments |
| 2026-09-20 | `3ffb91e` | G-16 boundary ratchet (8 cycles recorded) |
| 2026-09-20 | `ddd8d5d` | N-05 live smoke, 27/27 on production |
| 2026-09-20 | `38c40a9` | N-06 budget thresholds + configurable cap |
| 2026-09-20 | `c3a7b52` | N-08 guardrail at the send boundary |
| 2026-09-20 | `581232c` | this plan |
| 2026-09-20 | `38c22a3` | N-07 AI tool surface (+5 tools); RAG confirmed wired |
| 2026-09-20 | `37ad507` | **Job RUNNER** — the executor the control surface never had |
| 2026-09-20 | `383c989` | G-09 consent-checked door for promotional sends |
| 2026-09-20 | `24d60f9` | latent naive-timestamp drift on `segments.last_evaluated_at` |
| 2026-09-20 | `f2db93e` | **N-11** engine built lazily — four ops scripts were un-runnable outside CI; backfill applied to production |
| 2026-09-20 | `7f06d4d` | **N-09** SSE gateway now reads `lifecycle_state` (connect gate + mid-stream re-check) |

### Wave B outcome

Three builders and one adversarial reviewer ran in parallel on disjoint modules. **The reviewer
rejected one change outright and found four real defects plus five tests that could not fail** — all
fixed before commit. Two fixes were mutation-verified (the guard was disabled and the test confirmed
to fail).

The single most important thing this produced was not the features but the discovery that **the job
runner's first real execution exposed a latent pre-existing bug** (`segments.last_evaluated_at` was
declared naive while the migration created `timestamptz`) that had been sitting in the table for its
whole life because nothing had ever written it. That is the DoD rule earning its keep.

CI after the wave: **627 passed, 1 skipped** (was 564).

---

### Wave C outcome

Three builders + one adversarial reviewer, disjoint modules.

| Workstream | Deliverable |
|---|---|
| WS4 Integrity | `Idempotency-Key` (opt-in allow-list), atomic `If-Match`, layered tenant/user/endpoint rate limits |
| WS3 Platform | Billing metering + immutable period snapshots (§53–54) |
| WS1 Domain | Inbound media ingest pipeline + Attachment rows (§33–35) |

**The dominant finding: DEAD CODE, three instances.** `BillingSnapshotService` (zero callers *and*
it would have crashed on contact — it passed a constructor kwarg for a column that never existed),
`app/core/storage.py` (a complete port with no caller), and the job-runner registry from Wave B.

**The reviewer changed all three.** The worst: idempotency **deleted its reservation on any 5xx**, so
the retry re-executed the effect — and a test asserted `calls == 2`, locking the double execution in.
Also found: the whole `If-Match` surface had zero callers and was check-then-act; a media storage
failure rolled back `add_message` and **lost the customer's message**; billing **double-billed
overlapping periods**; `KEY_TTL` was written but never read.

**Two of my own mistakes, both caught by CI:**

1. `TypeError: 'extra' is an invalid keyword argument for Invoice` — every billing test. Fixed by
   adding the column.
2. **I then added that column to an already-applied migration.** Production was already stamped at
   `b3c4d5e6f7a8`, so Alembic would never re-run it: production would lack the column forever while a
   fresh database had it. Fixed by restoring the applied revision and adding `c4d5e6f7a8b9`.
   **A migration that has been applied anywhere is immutable.**

CI after Wave C: **717 passed, 1 skipped**. Production verified at `c4d5e6f7a8b9` with all three
columns present.

---

### Wave D outcome — the built-but-unused surfaces

Two items, both found by MEASURING rather than reading the plan.

**N-11 — production had no operational defaults.** `business_calendars`, `sla_policies` and
`subscriptions` were all **0 rows** across both live tenants, so SLA and entitlements were inert on
real data even though `seed_tenant_defaults` had been written and tested. The seeder only ran at
`register`, and both tenants predated it. Backfilled (calendar + SLA policy + budget policy), with
the plan binding left **opt-in** because `starter` permits only whatsapp + webchat and binding an
existing tenant to a plan could silently restrict a channel it already uses.

**The ops-script failure was measured, not assumed.** My own earlier note named
`rls_smoke_test` / `smoke_production` as broken; a subprocess probe with `ENVIRONMENT` and
`JWT_SECRET` unset showed the real set was `provision` / `seed_demo` / `configure_ai` /
`e2e_ai_test`. Root cause was one line: `app/core/db.py` built its engine at **module scope**, so
importing the module demanded a fully valid production configuration. The engine is now lazy, and
validation still fails closed — at first database access instead of at import.

**N-09 — the SSE gateway never read the tenant lifecycle.** Suspension was enforced on the request
path, the auth path and in the workers; `/realtime/events` was the one surface that skipped it, so a
suspended workspace kept a live firehose. Fixed at connect AND mid-stream, because the case that
matters is a workspace suspended while its inbox is already open.

**Fourth dead-code instance: `app/core/circuit_breaker.py`.** Nothing in `app/` imports it — only
its own unit test does. That is the Wave C finding repeating, and it is the reason G-13 is marked ⬜
above rather than ✅: a complete, well-tested module that no call path reaches is not a feature.

CI after Wave D: **728 passed, 2 skipped** (the two skips are Supabase-only migration guards).




| 2026-09-25 | `c6b7781` | Inbox read-model seeds bind the tenant GUC (CI-only refusal class) |
| 2026-09-25 | `c9ce795` | Desktop Phase 0 landed: pinned scaffold, 110/110, boundary gates |
| 2026-09-25 | `56a4163` | ai_usage uuid audit spelled legally + partition pins fixed |
| 2026-09-25 | `a134103` | Four CI tests write through a bound tenant GUC |
| 2026-09-25 | `3f5026d` | d8a1b2c3d4e5: the six phase-9 tables get canonical tenant_isolation |
| 2026-09-25 | `e4c3f2c` | Partition tests bind real datetimes; re-arm observed by re-select |
| 2026-09-25 | `b0d4619` | Tokenizer-safe CAST probes, real 360 read, isolated _HANDLERS |
| 2026-09-25 | `722ff8f` | R1: OpenAPI lock (245 ops / 112 typed) + drift gate + export tool |

### Wave E outcome — CI truth and the desktop merge

CI run 36136180924 was the first run in which the backend suite executed as
`sales_app` — the same non-superuser, RLS-enforced role production uses — and it
found **19 failures + 5 errors that a superuser connection could never see**.
Every failure was triaged to file:line and fixed at its owner, not muted: the
tenant-GUC bind class (7 tests), asyncpg's client-side type validation (4),
SQLAlchemy's `::` tokenizer refusal (2), a `Session.refresh()` clobber, a
min(uuid) aggregate, a test-only handler leak, and — the real catch — **six
tenant-scoped tables (`campaign_runs`, `journey_runs`, `journeys`,
`notification_digests`, `sagas`, `source_of_truth_policies`) that phase9 created
~30 revisions AFTER the b2c3d4e5f6a7 sweep with wrongly-named, unforced,
raising-guard policies**. Migration `d8a1b2c3d4e5` fixes the class dynamically
(add-only over every tenant_id table still lacking the canonical policy), not
the six names.

The desktop session's Phase 0 landed in the same close after Session A re-ran
its gates (`npm run verify`: 110/110, tsc, build, hardcoded-host OK), and its
critical-path request **R1 is delivered**: `desktop/openapi.lock.json` pins the
published schema (245 operations, 112 typed, sha256 in-file), measured by
`app/core/openapi_lock.py`, gated by `tests/test_openapi_lock.py` in the normal
backend job, regenerated by `scripts/export_openapi_lock.py` — typed coverage is
a ratchet that may only grow.

---

## 9. The ordered plan (2026-09-25) — what replaced the randomness

Everything below is ordered; each wave ends with **main green on CI** before the
next starts. "Green" means the run executed as `sales_app` — a skip is not a
pass, and `-rs` prints why.

**Wave F (held, lands first).** Four test-first files written against a spec
and held out of the tree until this close: `test_ai_contract.py` (19 RED),
`test_marketing_analytics_contracts.py` (18 RED), `test_customers_http_surface.py`
(7 RED, must not regress `test_customers_if_match.py`), `test_notifications_contracts.py`
(6 RED), plus the customers/notifications schema half and the marketing/customers
router partials (`partial-lanes.patch`). These are FEATURES, not fixes — the RED
suites define them.

**Wave SEC-1 (defects already named, small, do not scale).**
1. `/auth/switch-tenant` takes `tenant_id` as a query parameter
   (`identity/router.py:132-135`) while the "a tenant is never a parameter" guard
   pins `/api/v1/automation` only — widen the guard, fix the route.
2. Realtime accepts a long-lived access token as `?token=` and a stream survives
   token lifetime after the user is gone (`realtime/router.py:51-65`) — R5's
   short-lived stream-scoped credential is the fix, and it is the web client's
   exposure too.
3. The voice tables carry the same wrong-named phase-9 policies the six fixed
   tables had (no ORM model backs them, so the policy test cannot see them) —
   extend `d8a1b2c3d4e5`'s sweep or give them models.

**Wave API-1 (the desktop contract, R2–R8).** Ordered by what unblocks more:
- **R6** error-code enum with `retryable` mapping in the OpenAPI components —
  every feature's error state inherits it.
- **R8** `/auth/me` returns resolved permission codes — deny-by-default UI
  cannot enumerate affordances without it.
- **R2** per-operation idempotency markers + `Idempotency-Replayed` header —
  the Phase-3 offline-mutation ADR reads them.
- **R7** per-route ETag/If-Match declaration — optimistic UI reconciliation.
- **R3** `/search` through the existing `tsvector` columns (entity_type filter,
  rank, cursor) — ⌘K parity; today `core/search.py:57` is escaped ILIKE while
  generated tsvector columns sit unused.
- **R4** `Last-Event-ID` replay on the realtime stream — honest gap detection.

**Wave D-1 (desktop Phase 1 — unblocked by R1 as of `722ff8f`).** Codegen and
contract tests read the lock; error mapping reads R6's enum; Stronghold needs a
single-flight refresh across windows (two windows refreshing from a stale vault
copy log the user out everywhere — identity/service.py:383-399 rotates families).
The Rust side (`src-tauri/`, `Cargo.lock`, clippy/test/build) is verified the
first time `desktop-ci.yml` runs — until then nothing may claim it.

**Wave OPS-1 (measured gaps, no regression risk).** Worker counters for
`/metrics` exist but nothing increments them; the route-coverage figures in
GAP_REGISTER/ARCH_REVIEW are now unified by the lock script and the stale prose
should point at it; `ci.yml` keeps no `paths:` filter by decision (the backend
suite is the only DB-backed executor), but `desktop-ci.yml`'s runner budget
should be watched once native jobs run.

**The owner decides (§7 still open):** the SEC-1 vs API-1 order if both compete
for the same week; when `d8a1b2c3d4e5` reaches the production Supabase database
(apply is idempotent add-only); and whether plan-binding of existing tenants
stays opt-in now that defaults exist.

**The rule that produced this file:** nothing is "done" on a claim — a wave
closes when its commits are on main AND the CI run that executed them as
`sales_app` is green. Sections 4–6 are unchanged and still binding.
