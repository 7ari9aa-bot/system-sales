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

### Wave B — Make what exists actually work (in progress)
| Item | Team | State |
|---|---|---|
| N-01 entitlements | WS3 | ✅ closed |
| N-02 tenant suspension (API + auth + workers) | WS4 | ✅ closed |
| N-04 default privileges | WS4 | ✅ closed |
| N-05 provisioning seed + live smoke | WS6 | ✅ closed |
| **N-07 AI tool surface + RAG injection** | WS2 | ⬜ **next** |
| G-09 consent enforced at send | WS1 | ⬜ |
| G-13 circuit breaker wired | WS4 | ⬜ |
| **Job RUNNER (the executor behind the control surface)** | WS3 | ⬜ **biggest single gap** |

### Wave C — Breadth to reach the target
| Item | Team |
|---|---|
| G-08 outbox `locked_at` + replay | WS4 |
| G-14 `Idempotency-Key` on side-effecting writes | WS4 |
| G-15 `If-Match`/ETag optimistic concurrency | WS4 |
| §25 layered rate limits (tenant/user/endpoint) | WS4 |
| §33–35 media pipeline + Attachment | WS1 |
| §32 marketing consent entity | WS1 |
| §51–52 privacy + retention completion | WS3 |
| §53–54 billing metering + immutable snapshots | WS3 |
| §55–57 analytics read models, partition-ready, archiving | WS3 |
| §82 segments as a shared entity | WS3 |
| §65–67 security events + audit enrichment | WS6 |
| §114–116 security + performance test suites | WS6 |
| Playwright E2E in CI; frontend ESLint | WS5 |
| Remaining W5 surfaces (Customer 360 done; command palette done) | WS5 |

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
