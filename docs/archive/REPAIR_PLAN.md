# Architecture Repair Plan

This is the execution plan for closing the architecture gaps in dependency order.
It is intentionally stricter than the feature roadmap: a phase is complete only
when its acceptance checks pass.

## Current Baseline

- Local branch is synchronized with `origin/main`.
- Frontend production build passes for all routes.
- Playwright smoke coverage exists for Dashboard and Command Palette.
- Backend lint passes; database-backed tests are skipped until PostgreSQL and
  Redis are running locally.
- Completed in the current repair pass: configurable AI run limits, persisted
  AI timeout status, inbound consumer dedupe, scheduler registration and claim
  timing, payment reconciliation path, dashboard attention state, Tasks workflow,
  and global search wiring.

## Phase 1 — Executable Reliability Contracts

Goal: make durable processing behavior provable without provider credentials.

- Keep the AI limit, inbound dedupe, scheduler, and payment reconciliation fixes
  covered by focused tests.
- Add outbox cleanup and stale-lease recovery tests.
- Add event envelope compatibility tests for schema, aggregate, correlation, and
  causation fields.
- Add provider delivery reconciliation tests for out-of-order status events.
- Verify every worker binds tenant context before tenant-scoped queries.

Exit gate: focused backend tests pass, Ruff is clean, and every worker contract
has a test that fails when tenant binding or idempotency is removed.

## Phase 2 — Security, Tenancy, and Access

Goal: enforce the security model at every application boundary.

- Finish workspace/location authorization and resource-level checks.
- Add layered rate limits for auth, AI, webhooks, search, and bulk actions.
- Complete platform-admin and break-glass access boundaries.
- Move browser authentication toward HttpOnly secure cookies; keep token
  migration backward-compatible during rollout.
- Add security-event coverage for login failures, role changes, exports, and
  destructive privacy actions.
- Keep secret storage as references only; actual provider credentials are a
  deployment concern and are never committed.

Exit gate: RLS smoke, cross-tenant tests, authorization tests, and security
event tests pass.

## Phase 3 — Core Domain Completion

Goal: close domain correctness gaps before expanding UI surface area.

- Complete inventory reservation lifecycle: ACTIVE, EXPIRED, CONVERTED,
  CANCELLED, including order integration and expiry worker.
- Complete payment state machine and reconciliation webhook contract.
- Finish canonical message content and conversation lifecycle policies.
- Add consent, channel-account lifecycle, attachment/media states, and tombstone
  propagation where missing.
- Add explicit process state for order, payment, reservation, and fulfillment.

Exit gate: order/payment/inventory concurrency tests, provider event ordering
tests, and deletion/retention tests pass.

## Phase 4 — Frontend Product Workflows

Goal: turn the dashboard into the operating system described by the architecture.

- Rebuild Inbox around views, assignment, SLA risk, handover, and context tabs.
- Add Customer 360 with conversations, orders, payments, tasks, timeline, and
  identity history.
- Add saved views, URL state, bulk actions, notifications, health, and realtime
  recovery/resync.
- Replace remaining placeholders with API-backed workflows.
- Expand Playwright coverage across auth, inbox, orders, tasks, approvals, and
  failure states.

Exit gate: critical user journeys pass on desktop/mobile with loading, empty,
error, permission, RTL, and accessibility coverage.

## Phase 5 — Production Gate

Goal: prove operations, recovery, and deployment behavior.

- Run PostgreSQL and Redis locally/staging and execute all architecture gate
  scenarios instead of skipping them.
- Add Redis outage/replay, DLQ replay, tenant restore, deletion propagation,
  realtime reconnect, noisy-neighbor, and load tests.
- Add migration compatibility checks, backup restore drill, SLO/alert checks,
  and CI enforcement for module boundaries.
- Resolve dependency audit findings before production release.

Exit gate: all pre-production scenarios pass, staging deployment is repeatable,
and the release checklist is green.

## Working Rule

Each implementation slice must have one owning module, one focused validation
command, and no claim of completion based only on models or documentation.