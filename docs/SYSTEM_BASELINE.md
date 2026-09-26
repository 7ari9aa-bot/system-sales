# SYSTEM BASELINE — measured inventory before the V12 development program

Measured: 2026-09-26, from the code (three parallel read-only explorations), not from
any doc's claims. Branch state at measurement: `main` only, all four CI workflows green
at `533c3d6`. This file is the comparison anchor for the incoming V12 plan: every plan
item gets classified against it (NEW / COMPLETE-PARTIAL / FIX / ALREADY-DONE).

Related truth sources: `docs/COMPLIANCE_MATRIX.md` (spec §1–§177 verdicts),
`docs/GAP_REGISTER.md` (audit findings), `docs/ROADMAP_TO_90.md` (rubric + waves),
`docs/ADRS.md` (59 ADRs), `desktop/openapi.lock.json` (API contract, sha256-pinned).

---

## 1. Backend (FastAPI, `backend/`)

- 17 domain modules, ~242 route decorators across 29 routers under `/api/v1`; contract
  lock: **200 paths / 245 operations / 149 typed** (`tests/test_openapi_lock.py` drift
  gate). `/healthz`, `/readyz` (DB+Redis), `/metrics` (hand-rendered Prometheus).
- Eventing: transactional outbox writer + `OutboxRelay` (claim→publish→mark in ONE
  transaction, SKIP LOCKED reclaim, §128/§152 event_log) → Redis Streams consumer
  groups with `processed_events` inbox (§127), DLQ, XAUTOCLAIM.
- Workers: one process runs relay + 6 pools (`messages, notifications, webhooks,
  campaigns, scheduler, jobs`); scheduler owns 10 recurring jobs (reconcile UNKNOWN
  messages 5m, reconcile payments 15m, expire reservations 5m, expire approvals 10m,
  sla.sweep, retention.run, partition.ensure_months, purge_partitions,
  segments.recompute, journey resume).
- Cross-cutting core: tenant GUC binding (`bind_tenant`/`bind_scope`), layered rate
  limits (Lua), idempotency middleware + `Idempotency-Key`, UUIDv7, keyset pagination,
  conversation lease (§126), fairness budgets (§144), saga engine (§139), guardrails
  (§41/§173), consent gate, `contact_norm` (§27 E.164-ish), currency/money (§47),
  SearchPort (FTS + tsvector GIN; ILIKE fallback), partitioning (§56), storage
  (S3-compatible), circuit breaker, MFA (§146), break-glass (§147), field-level auth
  (§146), audit writer, secrets (DB-backed envelope store + rotation, §68 partial),
  structlog + `/metrics`.
- AI module (deepest): gateway (routing, provider policies §43 on both egress paths,
  budget reserve/settle §42), runtime (context builder with untrusted turns, §134 run
  limits), tools server-side-scoped (§132), durable approvals (§135 decide/resume/
  expiry), pgvector RAG with visibility (§157), governed memory (§158 provenance/
  invalidation/staff review), evaluations (§169 wired via routes), trace (§44).
- Migrations: **58 files**; groups: full schema + RLS sweeps (FORCE + canonical
  tenant_isolation policies, anon revokes), hierarchy §151, money §47 (tenant currency,
  invoice immutability triggers), AI governance (residency/retention, ANN indexes,
  approval dedupe, run limits), platform infra (event_log, processed_events,
  scheduled_jobs), FTS tsvector+GIN, ai_usage RANGE partitioning, contact backfill,
  restore_jobs, secret_values, MFA, service tokens.
- Tests: **206 files / ~2,205 tests**; special suites: `tests/gate/` (17 chaos
  scenarios: oversell, payment-UNKNOWN, n8n outage, Redis outage, DLQ replay,
  out-of-order receipts, tenant restore, realtime resync, tool-scope attack, stale-run
  cancellation, duplicate tool call, event schema compat...), `tests/security/` (role
  authz matrix over the real route graph, DB-backed tenant access matrix), `tests/perf/`
  (hot-path budgets), `tests/dr/` (restore drill script). CI executes the whole suite
  as `sales_app` on real Postgres+Redis; DB-gated cases skip locally — CI is the bar.

## 2. Frontend (Next.js 15, React 19, Tailwind v4, shadcn/Radix, `frontend/`)

- RTL-first (`dir="rtl"` hardcoded; strings-only ar/en toggle, both dictionaries
  complete; direction never flips). Root fonts: IBM Plex Sans Arabic.
- Complete surfaces: auth (login/signup/`/accept`), dashboard (merchant-day timezone
  honesty), inbox (713 lines; URL state `?view=`/`?conversation=`, SSE realtime with
  targeted cache patching, context panel), notifications centre + live bell,
  customers list + 360 (5 tabs) + drawer, orders list/record + full money/ops kit
  (create/refund/shipping/cancel/return dialogs, bigint minor units, idempotency key
  per dialog, If-Match), approvals queue, marketing + ROAS, products, inventory,
  tasks, settings (invitations/integrations/timezone), analytics overview, public
  marketing site (10 pages).
- Partial: my-work (read-only), AI page (knowledge/agents/usage only), operations page
  (raw `fetch` bypassing `api()` — known defect), palette search (2/5 entity types
  server-side), saved views (customers only).
- Thin (`as any`, 70–96 lines): journeys, leads, live, sla, queues, integrations, team.
- Data layer: single `apiUrl()` builder, token blob guard, single-flight refresh,
  `ApiError` with status/code/retryable, `Idempotency-Replayed` awareness, SSE client
  (fetch-stream, cursor resume, backoff). ~50 typed query hooks.
- E2E: **114 cases in 13 specs** against the production bundle (CI=1); gates:
  check:headers/urls/storage/palette wired into CI; `check-search-hits.mjs` exists but
  is NOT wired (Wave F held-out item).

## 3. Desktop (Tauri 2, `desktop/`)

Phase-0 scaffold by design: BootScreen + 2 commands (`app_info`, `log_write`) +
hardened redaction (13 secret + 12 PII key parts, JWT free-text detection, 400-char
truncation, depth cap) + platform port layer with enforced boundaries (no
invoke/fetch/storage outside adapters). `openapi.lock.json` = 37k-line contract anchor.
Gates (all green on windows-x64 + macos-arm64): JS boundary/typecheck/lint/vitest(110)/
build/host-scan; Rust fmt/clippy(-D warnings + unwrap/expect/panic denies)/test(6)/
`tauri build`. No user-facing features yet (Phase 1+ deferred).

## 4. Infrastructure & operations

- CI: `ci.yml` (backend on pgvector pg17 + redis as `sales_app`; frontend gates;
  Playwright e2e), `desktop-ci.yml` (paths desktop/**), `docker-publish.yml`
  (workflow_run-gated GHCR image from the green run's sha).
- Railway: Dockerfile builder, `preDeployCommand: alembic upgrade head`, healthcheck.
  Committed topology declares **API only** (`TOPOLOGY_START_GAPS["railway"]` guard);
  workers exist only via manual `scripts/deploy_railway.py`. A `staging` environment is
  defined in railway.json (secrets refs, feature flags) but nothing proves it is
  exercised. Frontend `vercel.json` rewrites to a hardcoded production Railway URL.
- Ops scripts (manual, idempotent): provision (RLS + sales_app role + seeds),
  smoke_production, backfill_metric_definitions, backfill_tenant_defaults,
  export_openapi_lock, deploy_railway, deploy_n8n, configure_ai, e2e_ai_test,
  load_test (p95<800ms webchat), rls_smoke_test, seed_demo.
- Config fails closed in secure environments (JWT ≥32B, no default service token,
  secrets master key required, CORS not `*`, Env secret store refused).
- **Known operational risks (measured):**
  1. `core/db.py` engine has no pool params → 15 connections; the two-connections-per-
     in-flight-event shape leaves **14/15 used** with the current 7 tasks — one added
     pool or nested session silently converts to 30s pool timeouts (GAP_REGISTER).
  2. Production Supabase stamped **25 revisions behind** local head
     `d8a1b2c3d4e5` (incl. the tenant-isolation policy sweep) — owner decision pending.
  3. No staging exercise, no backup/restore automation, alerts documented with zero
     backing config, no external secret store, no OTel export endpoint.

## 5. Spec compliance snapshot (from COMPLIANCE_MATRIX, 2026-09-25 count + verified stale rows)

```
113 rows:  71 fully implemented (62.8%)
           28 partial        (24.8%)
            0 missing after stale-row correction (§68-69, §164, §168 verified implemented)
           11 unscorable then; rescored with the full spec text: ~2 pass, ~7 partial,
              ~2 genuinely missing (channel test environments, external commerce SoT)
=> ~65% fully implemented, ~81% weighted (1/0.5/0). Strict 4-condition DoD rubric
   (ROADMAP §1) has not been re-measured since Wave E; CI-as-sales_app now satisfies
   its venue condition for the DB-backed suite.
```

Open named work (ROADMAP §9): Wave SEC-1 (3 small security fixes), Wave API-1
(desktop contract R2–R8), Wave OPS-1 (worker counters for /metrics, wire
check:search-hits), owner decisions §7 (staging G-03, Vault D-2, token storage D-5).
