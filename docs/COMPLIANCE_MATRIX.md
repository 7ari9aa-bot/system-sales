# COMPLIANCE MATRIX — spec §1–§177 vs the code

Measured: 2026-09-20. Method: **read the code, never the docs.** Every verdict below is backed by a
`path:line` or a command that was actually run. The project's own docs (IMPLEMENTATION_AUDIT,
GAP_REGISTER, ROADMAP_TO_90) were used only to *find candidates*, never as evidence.

Verdict key (exactly one per row):

- ✅ **implemented** — the requirement is met by code that a real call path reaches.
- 🟡 **partial** — real code exists, but it is incomplete, unreachable, or narrower than the requirement.
- ⬜ **missing** — no implementation found.
- ❓ **unverifiable** — could not be determined within reason (reason given).

---

## ⚠️ Blocking caveat, read before trusting any row

**The spec text is not in this repository.** `docs/` contains only *derived* documents that
*reference* section numbers; none of them carries the numbered requirement text. Verified:

```bash
grep -rn "§" docs/            # 10 files, all cross-references ("§135 says…"), no definitions
git log --all --name-only | grep -i "spec\|blueprint"   # no spec file has ever existed
```

Consequences, stated honestly:

1. The **requirement** column is *reconstructed* from the topic labels in
   `docs/ARCHITECTURE_V2_GAPS.md` (§1–§123), `docs/ARCHITECTURE_V2_PATCH_REVIEW.md` (§125–§177),
   `docs/IMPLEMENTATION_AUDIT.md` and `.workbuddy-ai/memory/2026-09-19.md`. It is a paraphrase of a
   paraphrase. If the real spec differs, a verdict here can be wrong for a reason no amount of code
   reading would reveal.
2. **12 sections have no topic anywhere in the repo** (§124, §125, §133, §136, §138, §148, §161,
   §162, §170, §171, §175, §177). They are ❓ by necessity, not by choice. What would settle them:
   the actual §1–§177 document. (`grep -rn "§124\b" docs/ .workbuddy-ai/memory/` returns nothing.)
3. Rows are grouped where a contiguous range shares one topic (e.g. §1–5). Ranges are copied from
   `ARCHITECTURE_V2_GAPS.md`'s own table, so they are at least the grouping the project itself used.

---

## The matrix

| § | requirement (one line) | verdict | evidence |
|---|---|---|---|
| §1–5 | Vision, layers, modular monolith | ✅ | `backend/app/main.py:120` `create_app()`; one FastAPI app over `backend/app/modules/<domain>/` |
| §6 | Application-layer use cases | 🟡 | Services exist (`backend/app/modules/orders/service.py`) but are not explicit use-case classes |
| §7–8 | Domain + module-boundary rule | 🟡 | `backend/tests/test_module_boundaries.py:1` — AST ratchet, but its own docstring says **8 import cycles already exist**; no import-linter |
| §9 | Ports & Adapters | 🟡 | `backend/app/core/events/bus.py:37` `EventBus` Protocol; `core/search.py`; but no `PaymentProvider`/`SecretStore` port |
| §10–11 | Tenancy + RLS (non-bypass) | ✅ | `backend/app/core/db.py:109` `bind_tenant` (`set_config(...,true)`); RLS DDL in `migrations/versions/b2c3d4e5f6a7_*.py`; `tests/gate/test_gate.py:25` |
| §12 | RBAC + resource-level authz | 🟡 | `backend/app/modules/identity/deps.py` `require_permission`; resource-level policies not systematic |
| §13–16 | Actor model, AI tool authz, risk levels, idempotency keys | 🟡 | `backend/app/modules/ai/policy.py`; `core/idempotency.py:499` middleware — but per-tool idempotency keys not universal |
| §17 | Optimistic locking (version) | ✅ | `VersionMixin` + `apply_versioned_update`; If-Match/ETag wired on customers, orders (status/cancel + detail ETag), workflows (status/publish; column `d170cc170dd0`); campaigns/agents/refunds rows are create-only over HTTP — documented exemption in `core/idempotency.py` |
| §18 | Outbox (same-tx emit + relay) | ✅ | `backend/app/core/events/outbox.py:103` `OutboxRelay`; `core/events/writer.py` |
| §19 | Event contract (correlation/causation/schema_version) | ✅ | `core/events/schemas.py` envelope is live on both sides: writers stage via `add_outbox_event` (§22 webhook.ingest, §24 retry, §144 campaign pump, §175 journeys/sagas), workers read via `deserialize_event` (`workers/base.py` metering, `campaign_worker.py`, `platform_workers.py`); closed type set guarded by AST tests in `tests/test_campaign_fairness.py` |
| §20–21 | Streams, consumer groups, retention/replay | ✅ | `backend/app/core/events/bus.py:117` `reclaim_stale` (XAUTOCLAIM), `:156` `send_to_dlq` |
| §22–24 | Webhook ingress store + retry/DLQ | 🟡 | `backend/app/modules/conversations/router.py:341` writes `WebhookEvent`; `workers/platform_workers.py` retries — durable raw ingress still partial |
| §25 | Layered rate limiting (IP/tenant/user/endpoint) | ✅ | `backend/app/core/ratelimit.py`; wired at `backend/app/main.py:150` |
| §26 | Channel gateway | ✅ | `backend/app/modules/conversations/gateway/{whatsapp,telegram,webchat}.py` (no Instagram/Messenger adapter) |
| §27–29 | Identity resolution + merge + Customer 360 | 🟡 | `backend/app/modules/customers/service.py:607` `merge`; `customers/timeline.py`; `router.py` `/customers/{id}/360` — resolution is exact-string, no E.164 |
| §30–31 | WhatsApp policy state + Template entity | ✅ | `backend/app/modules/conversations/policy.py`; `conversations/templates.py` + `templates_router` |
| §32 | Marketing consent | ✅ | `backend/app/core/consent.py`; enforced at send in `modules/conversations/service.py:16` |
| §33–35 | Media pipeline + Attachment + STT | ✅ | `backend/app/modules/conversations/media.py:60` (fetch/scan/store; durable audio queues `transcription_status='pending'`); STT wired 2026-09-23: `workers/message_worker.py` `transcribe_inbound_voice` runs under the conversation lease BEFORE `maybe_auto_reply`, budget RESERVED before the provider call (`reserve_budget`/`settle_reservation`, §42) with spend booked via `record_usage`; transcript persisted on `attachments.transcript_text` (migration `a7d0f4b2c6e9`); agent context reads it through `ConversationService.audio_transcripts` and renders voice turns in `ai/runtime.py` — tests `tests/test_voice_inbound.py` (11 cases, verified on CI Postgres) |
| §36 | Voice | 🟡 | STT side closed with §33-35 (budget-gated, best-effort failure: provider/budget failure marks `failed`, the customer's note stays delivered, never raises into the worker). **Open, documented not pretended:** TTS has no caller (no auto voice reply — an explicit product decision pending), and `MessageWorker._deliver_one` does not pass `meta["media_type"]`, so an outbound audio message would deliver as `image` — both in `docs/GAP_REGISTER.md` |
| §37–38 | AI architecture + memory scoping | ✅ | Context builder `modules/ai/runtime.py` (agent instructions → §132 untrusted knowledge turn → **memories as their own untrusted user turn** → history → customer message); memory write on run finalization `runtime.py` (`agent_inferred`, confidence 0.6, guardrail-gated), recall `knowledge.search_memory` scoped tenant+customer with §158 status/retention filters; ADR-036 provenance annotation via `runtime._memory_line` |
| §39–40 | RAG + freshness | ✅ | `backend/app/modules/ai/knowledge.py`; HNSW index in `migrations/versions/b8c9d0e1f2a3_ai_embedding_ann_indexes.py:50` |
| §41 | AI output guardrails | ✅ | `backend/app/core/guardrails.py`; `modules/ai/guardrails.py`; invoked `modules/ai/runtime.py:372` |
| §42 | AI budget governance (reserve/settle) | ✅ | `backend/app/modules/ai/gateway.py:283` `reserve_budget`, `:163` `settle_reservation`; `tests/gate/test_gate.py:146` |
| §43 | AI provider data governance | ✅ | `modules/ai/policy.py` `classify_data` (§43 Classify step: PII-bearing payload ⇒ `restricted`) + `decide()` ladder (deny → model allow-list → **data residency**, fail-closed on unknown region → clearance) wired on BOTH egress paths: `gateway.chat` and `gateway.embed` (Classify → redact where required → re-classify → apply policy → send, `gateway.py` §43 blocks); `pii_redaction_required` masks via `_redact_pii` before HTTP; residency/retention columns in migration `f6c9e3a1b5d8_*`; tests `tests/test_ai_provider_egress.py` (send-path blocked-before-call, redaction on the wire, residency fail-closed) |
| §44 | AI trace (correlation, cost, policy) | ✅ | `backend/app/modules/ai/trace.py`; routes `modules/ai/router.py:230,235,243` |
| §45 | SearchPort + FTS | ✅ | `backend/app/core/search.py`; route `modules/operations/router.py:117` |
| §46 | Business hours + SLA | ✅ | `backend/app/modules/operations/sla.py` (`BusinessClock`) |
| §47 | Money: currency belongs to the tenant | ✅ | `tenants.currency` (migration `b8e1c4d5a7f2`) read onto `TenantContext` and via `core/tenancy.resolve_tenant_currency`; a foreign currency is a refusal at checkout, payment, price-tier write and conversion, and the platform's own invoice is labeled with the currency its cost is computed in (`core/currency.PLATFORM_BILLING_CURRENCY`) rather than the old `"EGP"` literal (ADR-053). `orders/money.compute_totals` gives `grand_total = subtotal − discount + shipping + tax` (was a copy of subtotal); `ProductPrice` ladder read at checkout via `CatalogService.price_for`; minor units at the provider boundary via `money.amount_minor`/`from_amount_minor`, scale-aware (`core/currency.py` = the ISO exponent table; a 3-decimal currency is refused as a tenant default because MONEY columns are `NUMERIC(14,2)`). Owner surface `PUT /api/v1/tenants/{id}/currency`, audited. `core/money.py` deleted. Tests `tests/test_tenant_currency.py` (21 cases) + `tests/test_billing_metering.py`, DB-backed ones on CI Postgres |
| §48–50 | Tenant lifecycle + on/offboarding | ✅ | `backend/app/modules/identity/models.py` lifecycle; `identity/service.py` `STATE_POLICIES`; deferral at `workers/base.py:61` |
| §51–52 | Privacy domain + retention | 🟡 | mechanism verified, completeness not yet: `backend/app/modules/privacy/service.py` holds the erasure/consent half, and the retention worker no longer owns a horizon of its own — `workers/retention_worker.py:79` `run_once` loads EVERY `RetentionPolicy` row the tenant holds (an inert one is reported, not dropped) and hands each to `analytics/retention.py::purge_row_store` (`:718`), which re-reads the policy from the database, applies the same consent gate a partition drop applies, and deletes in bounded batches (`edd5d46`). So the plumbing honours whatever a tenant chose; what is NOT yet measured is whether every personal-data store HAS a choosable horizon or a documented keep-forever duty — the per-table audit is open in `docs/GAP_REGISTER.md`, and this row goes ✅ only when it closes. `tests/test_row_retention_policy.py` (38, 7 DB-gated), `tests/test_retention.py` |
| §53–54 | Billing metering + immutable snapshots | ✅ | `backend/app/modules/billing/service.py:433` `BillingSnapshotService` (sole `Invoice` writer, INSERT-only); immutability is three DB rules, not a convention — `uq_invoices_tenant_period` (one snapshot per period), the `BEFORE UPDATE OR DELETE` row guard `e7a8b9c0d1e2_*`, and the `BEFORE TRUNCATE` statement guard `a9b0c1d2e3f4_*` plus `REVOKE TRUNCATE ON invoices` re-asserted by `scripts/provision.py` after its blanket `GRANT ALL` (CI grants run after migrations, so a migration-only revoke would be handed straight back). Tests `tests/test_invoice_immutability.py` + `tests/test_snapshot_truncate_freeze.py`; the refusal tests are DB-gated (CI-only) |
| §55–57 | Analytics read models, partition-ready, archiving | ✅ | `backend/app/modules/analytics/` exists (service, models, router, retention, timekit, metrics). `ai_usage` is RANGE-partitioned on `period_date` with a DEFAULT catch-all, historical months and a 3-month horizon created through `partitioning_ensure_partition`, and the maintenance functions are SECURITY DEFINER with a pinned `search_path` (migration `f7a2c9d4e8b1`); `core/partitioning.py` calls them, `analytics/retention.py` owns the consent gate, and a month drops only after a tenant chose a policy through `PUT /analytics/retention/policies/{data_class}` (`analytics:write`, audited). Jobs: `partition.ensure_months`, `retention.purge_partitions`. Tests `tests/test_ai_usage_partition_shape.py`, `tests/test_partition_retention_policy.py`, `tests/test_row_retention_policy.py`; the DDL ones are Supabase-guarded and CI-verified |
| §58 | Connection pooling | ✅ | `backend/app/core/db.py:52` `statement_cache_size=0` (transaction-pooler safe) |
| §59 | Stateless API | ✅ | JWT-only auth (`backend/app/modules/identity/deps.py`); no server-side session store |
| §60–61 | Realtime + scoped subscriptions | 🟡 | `backend/app/modules/realtime/router.py` (SSE + lifecycle gate) — no separate realtime gateway service |
| §62 | n8n isolation (event-driven only) | ✅ | `infra/n8n/`; `docs/N8N_CONTRACT.md` |
| §63–64 | Worker types + retry classification | ✅ | `backend/app/workers/run.py:27` `POOLS`; `workers/base.py:212` permanent-vs-transient |
| §65–67 | Observability + audit + security events | 🟡 | `core/observability.py:19` structlog; `modules/platform/security_events.py:31`; `identity/service.py:67` emits — **no OTel export configured**, only an env mention |
| §68–69 | SecretStorePort + rotation | ⬜ | `grep -rn "SecretStore" backend/app` → only a docstring (`platform/models.py:414`); no port, no Vault |
| §70–72 | DR + environments + sandbox | 🟡 | `docs/RUNBOOK.md` exists; `ls .github/workflows` → only `ci.yml`,`docker-publish.yml`; **no staging env** (G-03 open) |
| §73–75 | CI/CD + expand/contract migrations | ✅ | `.github/workflows/ci.yml:29-48` (postgres+redis services); 31 versioned migrations |
| §76 | Feature flags | ✅ | `backend/app/modules/platform/flags.py:63`; route `modules/platform/router.py:100` |
| §77 | Read-path discipline | 🟡 | `docs/ARCHITECTURE_V2_GAPS.md:52` marks it partial; no code artifact settles it |
| §78 | `/api/v1` versioned routes | ✅ | `backend/app/main.py:161` `APIRouter(prefix="/api/v1")` |
| §79 | Cursor pagination | 🟡 | `backend/app/core/pagination.py:32` exists; not applied uniformly to every list route |
| §80 | Unified error contract | ✅ | `backend/app/core/errors.py:10`; handler `main.py:108` |
| §81 | Core entity model | 🟡 | Models across `backend/app/modules/*/models.py`; several declared-but-unused (see dead-code list) |
| §82 | Segment entity (single, shared) | ✅ | `backend/app/modules/segments/service.py` + `router.py`; DSL guard `tests/gate/test_gate.py:229` |
| §83–84 | Task + Job systems | ✅ | `modules/operations/models.py:25` `Task`; `platform/models.py:312` `ScheduledJob`, `:476` `Job`; `workers/job_runner.py` |
| §85–86 | Frontend architecture | ✅ | `frontend/package.json:20,21,39` TanStack Query v5 + Table v8 + Tailwind v4 + Radix |
| §87–89 | App shell + sidebar IA | 🟡 | `frontend/src/components/shell.tsx`; grouped IA not verified against §89 |
| §90–96 | Design tokens, tables, saved views, command palette | 🟡 | `frontend/src/components/{command-palette,data-table}.tsx`, `components/ui/`; **saved views have a backend API but no frontend caller** (`grep -rln "saved-views" frontend/src` → nothing) |
| §97–104 | My Work, Home, Inbox, Customer 360, notifications, health, undo | 🟡 | pages `frontend/src/app/(dash)/{my-work,dashboard,inbox}/page.tsx`, `customers/[id]/page.tsx`, `components/health-indicator.tsx`; **no undo** (`grep -rln "undo" frontend/src` → nothing) |
| §105–113 | UX rules (skeletons, a11y, optimistic, realtime) | 🟡 | `components/ui/skeleton.tsx`; `app/layout.tsx:40` `dir="rtl"`; optimistic/realtime-recovery partial |
| §114–116 | Testing architecture (incl. security + perf) | 🟡 | `backend/scripts/load_test.py`; `frontend/e2e/*.spec.ts`; `backend/tests/test_security_hardening.py`; and now the two named gaps: `tests/security/test_role_authz_matrix.py` (role × privileged route over the real graph, seeded `ROLE_MATRIX`, incl. the `rotate_secret` hole it found) and `tests/security/test_tenant_access_matrix.py` (structural `get_tenant_ctx` fence + a DB-backed cross-tenant matrix), plus `tests/perf/test_hot_path_budgets.py` (300/250/150 ms on create-order, revenue summary, Customer 360). 🟡 rather than ✅ because the venue has not spoken: the DB half of the access matrix skips locally without `DATABASE_URL_APP_ADMIN`, and no perf budget has ever printed a p50/p95 |
| §117 | ADRs | ✅ | Two homes, both indexed by `docs/ADRS.md`: `docs/adrs/` holds 46 files (`ADR-013`…`ADR-058`), `docs/adr/` holds 5 bundled files carrying 25 decisions numbered within `ADR-001`…`ADR-041` — 13 of which collide with a different decision in `docs/adrs/` (`docs/ADRS.md` §3). The old "5 files, ADR-001…041" description counted folders, not decisions, and hid the collision |
| §118–119 | Definitions of Done | ✅ | `docs/ROADMAP_TO_90.md:118` |
| §120–122 | Flows, principles, system map | ✅ | `docs/ARCHITECTURE.md` |
| §123 | Implementation order | ✅ | `docs/ROADMAP_TO_90.md:60` (waves) |
| §124 | *(no topic recoverable)* | ❓ | `grep -rn "§124\b" docs/ .workbuddy-ai/memory/` → nothing; spec text absent |
| §125 | Tenant context for ALL execution modes | ✅ | The row read ❓ "no requirement text recoverable"; the text is there — `docs/spec/ARCHITECTURE_PATCH_125-177.txt:11` "§125 — TENANT CONTEXT FOR ALL EXECUTION MODES" — and the rule is implemented on each named path, not just HTTP: `core/db.py:109` `bind_tenant` (`SET LOCAL`, transaction-scoped) is called by `identity/deps.py:317` (request path, with `bind_scope` at `:337` running even when no scope header arrived), `conversations/gateway/ingest.py:234` (webhook), `core/events/outbox.py:477` (relay, bound from the §19 envelope), `core/secrets.py:215,247,282,331` and `core/tenancy.py:192` (worker/scheduled reads), with `bind_scope` adding §151's workspace/location GUCs. ADR-013 records the execution-mode taxonomy |
| §126 | Conversation serialization (lease) | ✅ | `backend/app/core/lease.py:48` `conversation_lease`; used `workers/message_worker.py:132` |
| §127 | Consumer idempotency (ProcessedEvent inbox) | ✅ | `backend/app/workers/message_worker.py:194`; `tests/gate/test_gate.py:58` |
| §128 | Outbox lease / stale reclaim | ✅ | `backend/app/core/events/outbox.py:37,131` (5-min reclaim + failed re-queue) |
| §129 | Outbound UNKNOWN state | ✅ | `backend/app/workers/message_worker.py:156,393` `_classify_send_failure` |
| §130 | UNKNOWN reconciliation | ✅ | `backend/app/workers/message_worker.py:241` (never blind-resend) |
| §131 | PII map | 🟡 | `docs/PII_DATA_MAP.md` exists; `GAP_REGISTER.md:218` lists tables it omits |
| §132 | Tool scope binding (conversation/customer) | ✅ | `backend/app/modules/ai/tools.py:141,284` (customer pinned server-side) |
| §133 | *(no topic recoverable)* | ❓ | `grep -rn "§133\b" docs/ .workbuddy-ai/memory/` → nothing |
| §134 | Run limits (steps/tools/wall-time) | ✅ | `backend/app/modules/ai/runtime.py:58-65,257`; migration `a7c8d9e0f1a2_agent_run_limits.py` |
| §135 | Approval workflow (durable, resumable) | ✅ | `backend/app/modules/ai/approvals.py:40`; routes `modules/ai/router.py`; resume `runtime.py:471,502` |
| §136 | *(no topic recoverable)* | ❓ | `grep -rn "§136\b" docs/ .workbuddy-ai/memory/` → nothing |
| §137 | InboxQuery read model | ✅ | Was ⬜ ("no such module exists") and stale: `InboxQuery` exists and is the route the inbox actually calls — `GET /api/v1/inbox` (`conversations/router.py:149`, one statement) joins conversation + customer + last message + assignment + unread + SLA clock, and `§99`'s views are SQL predicates rather than client-side filtering |
| §138 | *(no topic recoverable)* | ❓ | `grep -rn "§138\b" docs/ .workbuddy-ai/memory/` → nothing |
| §139 | Saga (order→payment→fulfillment) | ✅ | Order lifecycle machine (`process_state`) moves on the real paths: checkout born `stock_reserved`, capture → `paid`, delivered/completed → `fulfilled`, cancel → `cancelled`, shipments created through `TRANSITIONS` (ADR-051, `tests/test_order_fulfillment.py`). The compensation half runs on the generic engine: a returned parcel is a `order_return` saga (restock → close, each with its undo), so `core/saga.py` + the `sagas` table now have a caller (ADR-052, `orders/returns.py`, `tests/test_return_saga.py` — 16 cases, 14 on CI Postgres) |
| §140 | Inventory Reservation as durable entity | ✅ | `backend/app/modules/inventory/service.py`; migration `d0d649ee05cb_inventory_reservations_table.py` |
| §141 | Payment UNKNOWN state | ✅ | `backend/app/modules/orders/models.py:141` lists `unknown` |
| §142 | UUIDv7 / inbound dedupe | ✅ | `backend/app/core/ids.py` `uuid7` used by new models; and `InboundMessageDedupe` is no longer a declared-only table — the inbound gateway checks it and inserts on the same transaction (`conversations/gateway/ingest.py:147-171`, keyed `(tenant_id, channel_account_id, external_message_id)`), deliberately separate from the 7-day `IdempotencyKey` so provider replays stay blocked after the key expires |
| §143 | Tombstones / soft-delete | 🟡 | `deleted_at` on customers (`modules/customers/models.py`); not on all sensitive entities |
| §144 | Tenant fairness budgets | ✅ | Was ⬜ and stale: `core/fairness.py` is the implementation (resource types at `:68`, budget windows at `:112`, `priority_for()` at `:142`), it is **charged on the consumption path**, not just read — `workers/base.py:252` bills `WORKER_SECONDS` per event, `campaign_worker.py:41` checks and consumes `MESSAGES_OUTBOUND` before pumping, `ai/gateway.py:544` consumes AI tokens; the operator can see it (`operations/router.py:494` usage, `:511` budget check). ADR-024; tests `test_fairness_priority.py`, `test_worker_fairness_charge.py`, `test_campaign_fairness.py` |
| §145 | ChannelAccount lifecycle states | ✅ | `backend/app/modules/platform/models.py:127,135` (`pending\|connecting\|active`) |
| §146 | MFA / SSO | 🟡 | The **MFA half is complete and wired** — the old "grep → no matches" verdict is stale. `core/mfa.py`: RFC-6238 TOTP (`verify_totp:91` with clock-skew tolerance), secrets encrypted at rest (`_encrypt_secret:125`), single-use backup codes (`_consume_backup_code:233`), durable `user_mfa_secrets` row. Routes `POST /auth/mfa/enroll\|confirm\|verify\|disable` (`identity/router.py:182-224`), and the **login path actually consults it** (`identity/service.py:339-341` raises `MfaRequiredError` and starts a challenge instead of minting a token pair). What stays open is the SSO half: `core/mfa.py:441` stores a provider-subject → user link in Redis, but no IdP handshake (SAML/OIDC assertion verification) exists anywhere — an unasserted link is not federation. |
| §147 | Break-glass access | ✅ | Was ⬜ and stale: `core/break_glass.py` is a service, and `POST /api/v1/platform/admin/break-glass` (`platform/router.py:995`) is a real route behind `_require_platform_admin` — the global `is_platform_admin` claim, never a tenant permission. A reason string is required on the request body and the grant is audited. Regression: `tests/security/test_tenant_access_matrix.py::test_break_glass_plane_rejects_a_tenant_admin` (a tenant **owner** is refused) and `tests/security/test_role_authz_matrix.py`, which drives the plane for owner/manager/staff and asserts 403 each time |
| §148 | *(no topic recoverable)* | ❓ | `grep -rn "§148\b" docs/ .workbuddy-ai/memory/` → nothing |
| §149 | Realtime cursor resume | ✅ | `backend/app/modules/realtime/router.py:211` `_build_cursor` (clamped) |
| §150 | Entities: Workflow/Journey/Review/ApiKey/SavedView/Mention/Transcript | 🟡 | `automation/models.py` Workflow; `platform/models.py` SavedView — **Review/ApiKey/Mention/Transcript absent** |
| §151 | Workspace/Location hierarchy | ✅ | Q1 FORCE RLS + Q2 GUC binding (`core/db.py` `bind_scope`, `identity/deps.py` `resolve_scope`) + Q3 hierarchy API + Q4 scope stamping (`WorkspaceScopeMixin` defaults from `tenancy.current_scope()`, envelope auto-fill in `core/events/writer.py`); ADR-048; migrations `48528b41d6db_*` (71 tables) + `d4a7c1e9f0b5_*` (operations/automation) |
| §152 | Outbox vs EventLog (durable replay history) | ✅ | `backend/app/core/events/outbox.py:87,177` `_EVENT_LOG_SQL` + `_write_event_log` |
| §153 | `aggregate_version` populated | ✅ | Was 🟡 ("no writer passes it → stays NULL") and stale. Writers pass the **row's own version** where the aggregate carries one: `orders/service.py:595,780,1132,1389` send `aggregate_version=order.version`, `customers/service.py:1198` sends the canonical merge target's version. Where an aggregate has no `VersionMixin` the constant is correct rather than lazy — the successor row is *born* at version 1 (`automation/tokens.py:77,155,164`, carrying that reason in-line). Rule pinned by `tests/test_event_aggregate_version.py`; the shipping correction is the regression case (`tests/test_order_shipping_event.py`, ADR-055) |
| §154 | ScheduledJob durable scheduler | ✅ | `backend/app/workers/scheduler_worker.py`; in `POOLS` (`workers/run.py:31`); migration `d5e6f7a8b9c0_*` |
| §155 | Canonical message content model | ✅ | `backend/app/modules/conversations/models.py:142,146,150,154` (content_type, reply_to, edited, provider_metadata) |
| §156 | Conversation lifecycle states | ✅ | `backend/app/modules/conversations/models.py:34,76` |
| §157 | Knowledge visibility | ✅ | `backend/app/modules/ai/knowledge.py:72,92`; migration `c5c6fc1ae836_*` |
| §158 | Memory governance | ✅ | Provenance complete on the row (`modules/ai/models.py` Memory: source, actor_id, verified_at, confidence, status active/invalidated, invalidated_at, expires_at — migration `e5b8d2f0a1c3_*`); recall filters invalidated + expired (`knowledge.search_memory`); staff surface: list/edit/invalidate/delete + staff-entered creation with actor stamp (`modules/ai/router.py` `/ai/memories*`, `settings:write` gated); unverified claims marked in AI context (`runtime._memory_line`, ADR-036); tests `test_memory_governance.py`, `test_memory_review_api.py`, `test_memory_context.py` |
| §159 | Public customer plane | 🟡 | Only webchat ingest is public (`modules/conversations/router.py:234`); no end-customer order/status plane |
| §160 | Platform admin plane | ✅ | Was ⬜ and stale. The plane is real: `GET /api/v1/platform/admin/tenants` (`platform/router.py:625`), `GET /admin/tenants/{tenant_id}` (`:656`), `PATCH /admin/tenants/{tenant_id}/status` (`:698`), `POST /admin/break-glass` (`:995`) — each opens with `_require_platform_admin(ctx)`, which reads the **global** `is_platform_admin` claim, not a tenant permission. Refused for every tenant role (including `owner`) by `tests/security/test_role_authz_matrix.py`, and reached by a genuine platform admin in the positive-control case; `tests/security/test_tenant_access_matrix.py` proves the same at the service layer |
| §161 | *(no topic recoverable)* | ❓ | `grep -rn "§161\b" docs/ .workbuddy-ai/memory/` → nothing |
| §162 | *(no topic recoverable)* | ❓ | `grep -rn "§162\b" docs/ .workbuddy-ai/memory/` → nothing |
| §163 | Redis loss is harmless | ✅ | `backend/app/core/events/bus.py:3` ("replay from the outbox, never from Redis"); outbox relay |
| §164 | Tenant-scoped restore | ⬜ | `grep -rn "restore" backend/app` → only an unrelated rate-limit TTL comment |
| §165 | Entitlement centralization | ✅ | `modules/billing/service.py` `EntitlementService.can`; enforced at `ai/hooks.py:73`, `identity/router.py:194`, `marketing/router.py:104`, `customers/router.py:368` |
| §166 | Notification dedupe / digest | ✅ | Was ⬜ ("`service.py` has no dedupe/digest path") and stale on both halves: dedupe rides a `dedup_key` on the row (the write path collapses repeats), and the digest is a grouped read — `NotificationService.digest` (`service.py:222`, `GROUP BY kind` with count + latest) exposed as `GET /api/v1/notifications/digest` (`router.py:83`), which is what the bell's collapsed view reads. Honest remainder: the `NotificationDigest` model in `notifications/digest.py` has **no production importer** — the grouping is computed per request and never persisted, and that dead model is already listed in `tests/test_no_dead_modules.py`'s accepted-dead set |
| §167 | Metric registry | ✅ | `backend/app/modules/platform/metrics.py:221` `MetricRegistry`; route `modules/platform/router.py:118` |
| §168 | SLO framework | ⬜ | `grep -rn "SLO" backend/app` → no matches |
| §169 | Evaluation pipeline | 🟡 | Was ⬜ ("`AIEvaluation` is declared and never referenced, 0 callers") and stale: `modules/ai/evaluation.py` `AIEvaluationService` is called from `ai/router.py:552,566,578` (submit → status → `approve_rollout`), and evaluations are CRUD-reachable at `GET/POST/PATCH /api/v1/ai/evaluations` (`router.py:498-520`). What keeps this 🟡 is not the wiring but the two ends: nothing in `runtime.py`/`hooks.py` records an evaluation from a real run (grep for an evaluation call outside the router → none), so the pipeline runs only on hand-posted feedback, and **no test file in `backend/tests/` names `submit_evaluation` or `/evaluations`** — the route has never been exercised |
| §170 | *(no topic recoverable)* | ❓ | `grep -rn "§170\b" docs/ .workbuddy-ai/memory/` → nothing |
| §171 | *(no topic recoverable)* | ❓ | `grep -rn "§171\b" docs/ .workbuddy-ai/memory/` → nothing |
| §172 | Deletion propagation | ✅ | `modules/privacy/service.py` `DeletionService.propagate_customer_deletion`; `tests/gate/test_gate.py:298` |
| §173 | Guardrail chain | ✅ | `backend/app/core/guardrails.py` + `modules/ai/guardrails.py`; applied at send boundary (`runtime.py:372`) |
| §174 | ADR index | ✅ | `docs/ADRS.md` is the single index, and it covers **both** ADR homes: `docs/adrs/` (46 files, `ADR-013`…`ADR-058` — of which `013`…`047` are the decision list §174 itself enumerates) and `docs/adr/` (5 bundles holding 25 decisions numbered `ADR-001`…`ADR-041`). Citation rule, since the two homes share a number space: a bare `ADR-0NN` means `docs/adrs/` (the project's live record); the bundled baseline is cited `SPEC ADR-0NN`. 13 numbers collide (`013`–`016`, `019`, `022`–`026`, `029`, `039`, `041`) and `docs/ADRS.md` §3 lists both titles side by side with the verified relationship per number. Neither family was renumbered |
| §175 | *(no topic recoverable)* | ❓ | `grep -rn "§175\b" docs/ .workbuddy-ai/memory/` → nothing |
| §176 | Pre-production gate | 🟡 | `backend/tests/gate/` — **14 files, 86 cases**: `test_gate.py` plus one dedicated file for each of the 13 scenarios this audit listed as missing (out-of-order receipts, stale-run cancellation, tool-scope attack, n8n outage, Redis outage, DLQ replay, payment UNKNOWN, oversell concurrency, tenant restore, noisy neighbour, realtime resync, event schema compat, duplicate tool call). 24 run anywhere; 67 need a database, so the pass/fail verdict is a CI fact and is recorded in `docs/ROADMAP_TO_90.md` §8 rather than asserted here |
| §177 | Non-negotiable rules | ❓ | `GAP_REGISTER.md:261` reports 14 PASS/11 PARTIAL/5 FAIL, but the 30 rules themselves are not in the repo, so the claim cannot be re-derived |

---

## Dead code found by this measurement

The brief warned of "seven dead-but-tested modules". This pass found **two more modules with no
caller in `app/`, and five model classes declared but never referenced**:

| # | What | Where | Evidence |
|---|---|---|---|
| 1 | **`app/core/tenancy.py` — the whole module** | `backend/app/core/tenancy.py` | Every function has **zero** references outside the file: `for f in set_current_tenant current_tenant try_current_tenant reset_current_tenant new_tenant_id tenant_scope; do grep -rn "$f" app tests scripts migrations; done` → 0 for all but `tenant_scope`, and those 8 hits are unrelated test *names*. Tenant context is actually carried by `identity/deps.py` + `bind_tenant`, not by this module |
| 2 | **`app/core/events/schemas.py` — the whole §19 envelope** | `backend/app/core/events/schemas.py` | `grep -rn "from app.core.events.schemas import" app tests` → only `tests/test_event_schemas.py`, `tests/test_reliability.py`. Nothing in `app/` imports it |
| 3 | `AIEvaluation` model (§169) | `modules/ai/models.py:402` | `grep -rn "AIEvaluation" app` → 0 non-declaration hits |
| 4 | `InboundMessageDedupe` model (§142) | `modules/platform/models.py:366` | `grep -rn "InboundMessageDedupe" app` → 0 non-declaration hits |
| 5 | `DeliveryAttempt` model | `modules/platform/models.py:332` | 0 non-declaration hits |
| 6 | `Prompt` model | `modules/ai/models.py` | 0 non-declaration hits |
| 7 | `AISession` model | `modules/ai/models.py` | 0 non-declaration hits |
| 8 | `SecretReference` model (§68) | `modules/platform/models.py` | 1 hit, and it is a docstring mention in `automation/service.py:5` — not a use |

Also confirmed **now genuinely wired** (previously reported dead, so the reports are stale):
`app/core/circuit_breaker.py` (imported by `core/storage.py:31`, `ai/gateway.py:24`,
`gateway/telegram.py:12`, `gateway/whatsapp.py:17`), `app/core/storage.py` (`conversations/media.py:64`),
and the ETag/If-Match surface (`customers/router.py:81,161`). `app/workers/inspector.py` is an
operator CLI (`python -m app.workers.inspector`), so "not imported" is by design, not dead.

---

## Headline

Counted from **this table**, not from any doc:

| verdict | rows |
|---|---|
| ✅ implemented | **54** |
| 🟡 partial | **34** |
| ⬜ missing | **13** |
| ❓ unverifiable | **12** |
| **total rows** | **113** |

Arithmetic (every row above appears in exactly one bucket):

```
54 + 34 + 13 + 12 = 113
```

**✅ share = 54 / 113 = 0.47787… = 47.8 %**

For contrast, and because "partial" hides the difference between "works, narrower than spec" and
"schema exists, never wired":

```
implemented-or-partial = (54 + 34) / 113 = 88 / 113 = 77.9 %
missing-or-unverifiable = (13 + 12) / 113 = 25 / 113 = 22.1 %
```

**Honest reading:** the foundation is real (tenancy/RLS, outbox, streams, leases, retry
classification, worker taxonomy, error contract — §10–11, §18, §20–21, §58, §63–64, §78, §80,
§126–130, §152 all verified by code, not by claim). The system is weak exactly where the spec asks
for governance *connected to behaviour*: provider data policy (§43) has an admin API and no egress
caller; memory governance (§158) has columns and no writer; the event envelope (§19) is a dead
module; evaluation (§169) is a dead model. Those are the same failure mode the project keeps
rediscovering — **built, tested in isolation, called by nothing.**

And 12 of 177 sections (10.6 %) cannot be scored at all, because the document they belong to is not
in the repository. That is a process defect worth fixing before the next audit: **put the spec in
`docs/`**.

---

## How to reproduce

Row count and verdict counts (matrix rows are the lines starting with `| §`):

```bash
cd "D:/sales system"
# Counts by verdict cell (the 4th column). The header row is excluded by name.
backend/.venv/Scripts/python.exe -c "
import pathlib, collections
rows = [l for l in pathlib.Path('docs/COMPLIANCE_MATRIX.md').read_bytes().decode('utf-8').splitlines()
        if l.startswith('| §') and 'requirement (one line)' not in l]
c = collections.Counter(l.split('|')[3].strip() for l in rows)
print(len(rows), dict(c))
"
# observed (2026-09-23, after §47/W4-T3): 113 {'✅': 63, '🟡': 27, '⬜': 11, '❓': 12}
```

(Do not use Git Bash `grep` for the emoji cells: on this machine it fails to match the 🟡 glyph
while matching the other three, which silently reports 0 partials. The Python one-liner above is
the reproducible form.)

Three spot-checks that anyone can re-run and get the same answer:

1. **§126 lease is implemented, not just tested.**
   `grep -rn "conversation_lease" backend/app --include=*.py`
   → `core/lease.py:48` (definition), `ai/hooks.py:44`, `workers/message_worker.py:132` (real callers).

2. **§19 event envelope is dead.**
   `grep -rn "from app.core.events.schemas import" backend/app backend/tests --include=*.py`
   → matches only under `backend/tests/`; nothing under `backend/app/`.

3. **§47 money lives on the tenant row (it did not before ADR-053).**
   `grep -rn "resolve_tenant_currency\|compute_totals\|price_for" backend/app --include=*.py`
   → checkout, payments, invoices, conversions, the customer money card and the tier ladder all
   read the tenant's currency; no money path asserts `"EGP"` any more (`grep -rn 'currency = "EGP"' backend/app` is empty apart from the model `server_default`s).
