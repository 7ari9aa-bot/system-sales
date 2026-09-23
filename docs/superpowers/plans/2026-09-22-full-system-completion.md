# Full-System Completion — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Executed wave-by-wave; each wave gets its own detailed task plan before dispatch. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Sales OS to 100% internal completeness against the 177-section architecture spec, leaving ONLY external credential-dependent integrations (Meta/WhatsApp/Telegram/AI providers/Stripe/SMTP) pending.

**Architecture:** Modular monolith (FastAPI backend + Next.js frontend) per docs/ARCHITECTURE.md. Work proceeds in waves mapped to the 6 disjoint workstreams (WS1 domain/channels, WS2 AI, WS3 platform, WS4 security, WS5 frontend, WS6 ops) so parallel agents never touch the same files.

**Tech Stack:** FastAPI + async SQLAlchemy + Alembic, Postgres (RLS, pgvector) on Supabase, Redis Streams, Next.js 15 + React 19 + TanStack Query + Radix + Tailwind v4, Railway + Vercel + GitHub Actions.

**Spec:** `docs/spec/ARCHITECTURE_SPEC_1-124.txt` (§1–§124) + `docs/spec/ARCHITECTURE_PATCH_125-177.txt` (§125–§177; **patch wins conflicts**). Gap evidence: 2026-09-22 six-agent audit (this file's wave scopes cite it).

## Global Constraints

- PostgreSQL + Domain = the only source of truth; all mutations via Application/Domain services; events via Outbox in the same transaction; Redis is transport, never truth; tenant isolation enforced twice (app-layer + RLS).
- **Zero deferral** (MASTER_PLAN directive 2026-09-18): nothing technical is deferred; only external platform credentials wait.
- Definition of Done per item: implemented per spec + test that fails-before/passes-after + runs on real Postgres in CI.
- **Agents never run git** and never revert/overwrite pre-existing uncommitted changes (in-flight webhook/inbox work exists in the working tree — diffs must be minimal and additive).
- **DB-backed tests are verified by the orchestrator/CI, not by agents** (AGENT_BRIEF convention): agents run `ruff` and `pytest --collect-only` locally; the orchestrator runs DB suites in CI or against a test database.
- After EVERY wave: 2 review agents (gap-hunting only, no new features) → findings in `docs/reviews/wave-N.md` → blockers fixed before wave N+1.
- No new dependencies without checking `pyproject.toml` / `package.json` first; follow existing module layout (`models.py`, `service.py`, `router.py`, `schemas.py`).

---

## Wave 0 — Live correctness bugs (parallel, 5 independent fixes)
Plan: `docs/superpowers/plans/2026-09-22-wave-0-live-bugs.md`

- [ ] W0.1 AI auto-reply RAG silently broken: `ai/hooks.py:119` imports nonexistent `retrieve_relevant` from `ai/knowledge.py`; ImportError swallowed at `hooks.py:130` → every auto-reply runs with zero knowledge. Implement the retrieval function + regression test that fails on the import.
- [ ] W0.2 Orders Undo broken: `frontend/src/app/(dash)/orders/page.tsx:154` posts relative `/api/orders/{number}/cancel` (wrong origin, number≠id) → 404 in prod. Use apiClient + order id + e2e/unit evidence.
- [ ] W0.3 `notifications/digest.py` is dead code carrying a duplicate `notification_preferences` table mapping that would crash mapper init if imported → make it import-safe (reuse the existing model); wiring lands in Wave 4 (§166).
- [ ] W0.4 Channel-account lifecycle unenforced: `validate_transition` dead code; `customers/router.py:376-417` upsert writes status directly → enforce transitions + test illegal transition rejected.
- [ ] W0.5 `aggregate_version` hardcoded literals (e.g. `orders/service.py:338`) → real per-aggregate version; event-contract test asserts monotonic versions (§153).

## Wave 1 — Security & data-integrity blockers (WS4 + WS3)
- [ ] §164 Tenant-scoped restore functional: `platform/tenant_restore.py:242-254` `_extract_entity` returns 0 → real export→validate→execute chain + gate test (delete tenant data, restore, verify rows).
- [ ] §136 n8n→core auth: replace global `service_token_internal` (`config.py:109`, `automation/service.py:250`) with tenant-scoped credentials (per-tenant service tokens, scoped callback endpoints).
- [ ] §146 MFA wired into login; TOTP secrets out of process memory (`core/mfa.py:94`) → DB/Redis store; API keys entity + rotation; OAuth scopes.
- [ ] §59/§147 break-glass capability tokens → Redis store (survive replicas/restart); token unlocks a real elevation path; audit to `security_events`.
- [ ] §66/§177.5 audit_logs += `source`, `request_id`, `correlation_id` (migration + populate from middleware/actor context; AI actions distinguishable).
- [ ] §68/§69 secrets: encrypt `integrations.credentials` at rest (SecretStorePort impl), secret-access audit, `secret_rotated` security event, rotation validate step.

## Wave 2 — Structural hierarchy & eventing (WS4 + WS1)
- [ ] §151/§10 RLS hierarchy: workspace_id/location_id reflected in policies (expand-contract migration), tenant context carries workspace/location everywhere (§125).
- [ ] §19/§153 event envelope += workspace_id/location_id; per-aggregate ordering key; consumer ordering/version checks possible.
- [ ] §144 tenant fairness: enforce concurrency constants (`tenancy.py:23`) + priority ordering beyond AI budgets.
- [ ] §22 webhook ingress: ACK-quick + async processing (out of the HTTP request path).
- [ ] §24 DLQ ops: inspect/ignore/mark-resolved + `.dlq` stream management (admin plane).
- [ ] §17 If-Match/ETag beyond customers/orders (all mutating entity endpoints).

## Wave 3 — AI platform completion (WS2)
- [ ] §39/§40 knowledge: chunking/parsing pipeline, document versions + freshness states (stale/fresh/reindexing), re-index path, metadata (permissions/language), reranking.
- [ ] §157 visibility levels in ingest API + permission/agent-policy retrieval filters.
- [ ] §158 memory governance: staff review/edit/delete/invalidate endpoints + allowed-types policy.
- [ ] §132 untrusted boundary: customer memory text out of the system-prompt role.
- [ ] §134 enforce max_retries/max_handoffs; §16 tool-idempotency tests; §44 trace real fields (prompt_version/retries/policy_decisions/request_id) + tests + user-facing trace surface.
- [ ] §169 evaluation pipeline wired: monitor worker ramps canary, runtime routes canary traffic, offline eval execution + regression comparison + tests.
- [ ] §43 provider governance: data classification (not hardcoded "internal"), residency/retention fields, fail-closed default.

## Wave 4 — Commerce & business systems completion (WS1 + WS3)
- [ ] §139 order saga: real process manager (event-driven transitions, compensation policy) — `transition_process_state` gets callers; paid/stock_reserved/fulfilled reachable.
- [ ] §53 metering: usage-event envelope (usage_event_id/unit/source/idempotency_key) + dedup; meter messages/campaigns/automation.
- [ ] §161 external commerce wired: router + worker + tests for SourceOfTruthPolicy/CSV/Shopify adapter (or remove if superseded — zero-deferral says wire).
- [ ] §55/§56/§57 analytics: read models/consumers or documented pre-aggregation; PARTITION BY on hot tables (messages/audit/ai_usage/webhook_events); archiving worker scheduled.
- [ ] §45 search: tsvector/trigram + GIN + indexer consumer replacing ILIKE.
- [x] §47 money: closed by W4-T3 with the ADR branch — `tenants.currency` per tenant (ADR-053), `NUMERIC(14,2)` kept and justified there, minor units derived at the provider boundary (`orders/money.amount_minor`, scale-aware), foreign-currency writes refused, `grand_total` computed from discount/shipping/tax, price ladder read at checkout. Cross-currency exchange-rate persistence is unmet by design (one currency per tenant ⇒ no pair to report).
- [ ] §166 notifications: wire digest/aggregation/quiet-hours (after W0.3), NotificationDelivery entity, email/push dispatcher, SLA-escalation chain.
- [ ] §167 metric definitions: business_hours_rule/aggregation attrs, conversion_rate/roas handlers, seed_definitions wired, marketing uses registry.
- [ ] §81/§150 missing entities: ApprovalStep/ApprovalDecision, InvoiceLine, ApiKey, Transcript, OutboundMessage, BusinessHours/Holiday tables, Mention, Favorite, Review, DeletionJob, Queue/Incident/SystemEvent (per spec's canonical list).
- [ ] §28/§29/§27 customers: tasks remap on merge, AI-assisted merge-candidate endpoints + AI caller, 360 adds marketing/journeys/reviews/AI-interactions/consent.
- [ ] §30 Conversation.channel_account; §156 reopen-after-closed policy + channel-configurable lifecycle.
- [ ] §33 media: quarantine + scan statuses enforced, metadata extraction, signed URLs; §35/§36 voice: wire STT/TTS into ingest, telephony adapter behind port (credential-gated stub with contract tests).

## Wave 5 — Frontend completion (WS5; use senior-frontend + design-review + playwright-testing skills)
- [ ] §149 realtime recovery: connection_id, permission re-check on reconnect, authoritative resync after resume, revoked-subscription handling.
- [ ] §94 table system: advanced filters, grouping, column visibility, density, bulk actions, export.
- [ ] §105 progressive disclosure (Basic→Advanced→Technical); §89 shell: AUTOMATION group, role-based visibility, Favorites/Recent.
- [ ] §110 performance: list virtualization, route code-splitting, bounded fetches, perf-budget check script in CI.
- [ ] §95 saved views scoping (Private/Team/Workspace) + fix dead orders selector; §87 URL state for orders/analytics; §88 entity pattern for orders/products.
- [ ] §97 My Work (+follow-ups/mentions/AI handoffs), §98 Home personalization, §100 customer record missing tabs, §101 workspace activity feed, §102 notifications priority tiers + Needs Action.
- [ ] §106 requestId propagation; §107 mobile bottom nav + tablet rail; §108 44px touch targets.
- [ ] Extend e2e: critical-flow coverage per §114 (playwright-testing skill).

## Wave 6 — Ops, environments & gate completion (WS6; use ci-cd-architecture skill)
- [ ] §170/§72 channel testing environment: environment-scoped channel credentials/webhooks/templates + Meta sandbox config (credential-gated).
- [ ] §61 realtime scoping: workspace/role-aware subscriptions.
- [ ] §63 remaining worker pools (AI/media/STT/analytics/billing/privacy/campaign as needed by waves 3–4).
- [ ] §67 security events: role/permission changed, secret rotated, API key created, webhook changed, integration connected, data export.
- [ ] §52 retention: all 7 data classes + archive tier; event_log/outbox retention enforced.
- [ ] §49/§50 onboarding pipeline (trackable/resumable steps) + offboarding (revoke integrations/secrets, cancel subscription).
- [ ] §70 backup/PITR config + scheduled restore drills.
- [ ] §73 CI: type-check + security-scan stages, staging→prod promotion gate.
- [ ] §114/§116 testing: FE component/a11y/RTL tests; perf scenarios (noisy-neighbor/backlog/connection-pressure) into CI.
- [ ] §162 runtime topology: workers/relay/realtime as defined Railway services.
- [ ] §163 real Redis-outage test (kill redis, assert outbox buffering + replay).
- [ ] §168 SLO: alert destinations/owners/runbooks + delivery wiring.
- [ ] §176 gate → 23/23 real scenarios (remove proxies: out-of-order provider events, tenant restore, noisy-neighbor; real n8n/redis outage exercises).

## Exit criteria (whole initiative)
- All 168 scored sections at complete=1 per the audit rubric, verified by a closing 6-agent re-audit.
- §176 gate 23/23 real; CI green (ruff + full pytest incl. DB + FE lint/build/e2e); review findings log closed for every wave.
