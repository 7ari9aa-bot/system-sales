# GAP REGISTER — Full-System Critique Audit

Date: 2026-09-19 · Method: 8 critique squads (security, concurrency/reliability, commerce
domain, AI-safety, API contract, frontend, ops/data/testing, spec-compliance §1–§177).
Every file read in full; the most severe claims independently re-verified by the lead.

This register is the build input. Nothing here is documentation-based — everything is
file:line evidence from code. Fix order proposal is in §8.

## 1. Executive summary

- ~200 distinct findings across 8 domains. Severity: 15 CRITICAL, ~45 HIGH, rest MEDIUM/LOW.
- The architecture skeleton is real (outbox, RLS plumbing, leases, retry/DLQ, worker
  taxonomy). The system breaks exactly where correctness, security, and merchant value
  live: a dozen wired-but-wrong paths, a larger set of built-but-dead paths, and three
  security holes that end-to-end compromise the product.
- Claimed vs real: CI executes ~67/178 tests (no DB service in CI); the §176 gate passes
  9/23 scenarios; `alembic upgrade head` fails on a fresh database; RLS exists only in a
  script, not in migrations.

## 2. CRITICAL — build-blockers (fix before ANY new feature)

### C1. Cross-tenant SSE event leak + full history replay
`backend/app/modules/realtime/router.py:180-202` — reads `payload.get("meta")`, but the
relay publishes `payload` and `meta` as separate Redis fields (`core/events/bus.py:64-74`),
so `meta.tenant_id` is always absent and the tenant filter never fires. Every authenticated
user receives every tenant's message bodies, orders, notifications. `?cursor=0-0` replays
the entire retained stream (100k entries). Fix: read the `meta` Redis field, fail-closed
tenant check, clamp cursor to connection time. VERIFIED by lead.

### C2. Unauthenticated message injection via `/webhooks/webchat`
`conversations/gateway/webchat.py:26-27` (`check_signature` returns True) + registry
registers webchat in the webhook dispatcher (VERIFIED) + `resolve_tenant_key` reads the
attacker-controlled `public_key` from the JSON body. No pydantic validation on this path
(no 4096 body cap). Anyone can inject messages into any tenant that has a webchat widget.

### C3. Outbound-message claim is not atomic → double-send to customers
`app/workers/message_worker.py:193-268` — SELECT then ORM write, no `FOR UPDATE`, no
conditional `UPDATE ... WHERE status='queued'`. Two deliveries of the same message both
pass the guard → provider called twice. Combined with C5, duplicates are guaranteed.

### C4. Consumer-inbox dedupe keyed on a per-publish-random id
`core/events/bus.py:67` writes `fields["id"] = str(uuid.uuid4())` fresh on every XADD;
`message_worker.py` keys `ProcessedEvent.event_id` on it. The outbox relay re-publishes
after crash-reclaim (`core/events/outbox.py:37-44`) with a NEW uuid → dedupe never hits →
duplicate AI replies/messages. VERIFIED by lead. Fix: carry the outbox row id in `meta`
and dedupe on it.

### C5. Outbox `failed` rows and attempts-exhausted pending rows are stranded forever
`outbox.py:46-68` — nothing ever re-claims `failed`; reclaim resets stranded `publishing`
to `pending` even when `attempts >= max` (then no query selects it). Redis outage of
minutes = events silently never published. No replay tool exists.

### C6. No PEL reclaim (XAUTOCLAIM) anywhere
`bus.py` only XREADGROUPs `>`; a worker killed after read, before ack, strands entries in
the pending list forever — invisible message loss. Fix: periodic XAUTOCLAIM in StreamWorker.

### C7. `message.received` failures are swallowed → reply silently lost
`message_worker.py:122-125` catches everything (acks the event; ProcessedEvent marker
rolled back) and `ai/hooks.py:47-50` swallows `ConversationBusy` (retryable by contract).
AI provider hiccup = customer message never answered, never retried.

### C8. Approval workflow crashes the DB and is a dead end
`ai/models.py:182` `status String(15)` vs `"WAITING_APPROVAL"` (16 chars) → first HIGH-risk
tool call raises DataError (VERIFIED). `decide()`/`expire_stale()` have zero callers; no
endpoint; no resume; loop does not suspend (duplicate ApprovalRequests per run).

### C9. Sold stock is never deducted — permanent phantom stockouts
`inventory/service.py:414-432` `convert()` flips reservation rows but never decrements
`balance.reserved`; no movement written; no expiry worker exists (scheduler never gets
work: see C12). Every paid order permanently shrinks availability. The AI/checkout path
will progressively stop selling.

### C10. No API can create a payment or a refund — orders cannot leave `pending`
`orders/router.py` exposes no payment-create, no refund, no cancel routes;
`add_payment`/`register_refund` are service-only. Combined with C9, the commerce loop is
closed nowhere. `reconcile_payment` requires payment rows nothing creates.

### C11. Fresh `alembic upgrade head` fails; local DB cannot even run migration 1
`migrations/versions/f8a1c2d3e4b5` duplicates column ops from `6cd2037d7891` (VERIFIED);
`infra/docker-compose.yml:3` uses `postgres:17-alpine` with no pgvector and no migration
runs `CREATE EXTENSION vector`. No environment can be built from the migration chain.

### C12. RLS lives only in `scripts/provision.py` — not in migrations
Grep-verified: only `e1f2a3b4c5d6` (notifications) has RLS DDL, with a divergent policy
name and no NULLIF guard. A migrated-but-unprovisioned DB has zero tenant isolation while
`sales_app` holds ALL privileges. Also: many public/auth paths (webchat ingest,
`/auth/me`, `switch-tenant`, `accept_invitation`) never bind GUCs — under enforced RLS
they break, so production is almost certainly running with RLS bypassed (app-layer
scoping as the only defense).

### C13. Rate limiting is effectively OFF: prefixes never match + spoofable keys
`core/middleware.py:42-51` checks `/auth/`, `/webchat/`, `/webhooks/` but all routes live
under `/api/v1/...` → auth runs in the 300/min generic bucket and fail-closed is
unreachable. `_client_ip` takes the LAST XFF hop → per-request spoofed keys. INCR/EXPIRE
non-atomic (immortal keys).

### C14. Frontend: XSS via `media_url` href + logout keeps sessions alive
`frontend/src/app/(dash)/inbox/page.tsx:416-428` renders `m.media_url` as raw `<a href>`
(VERIFIED) — `javascript:` URLs steal `localStorage` tokens (account takeover chain).
`components/shell.tsx:203-206` never calls `POST /auth/logout` and never clears the
TanStack cache — refresh token stays valid; next login flashes the previous account's data.

### C15. Deployment topology is incoherent
Root `vercel.json` is not valid Vercel schema; two divergent `railway.json` files
(healthcheck in only one); `deploy_railway.py` defaults the admin DSN to the transaction
pooler (violates its own rule) and rotates Redis password/JWT secret on every deploy;
`deploy_n8n.py` passes service id as environmentId; the pre-deploy migration fails per C11
anyway; `pyproject-prod.toml` is dead and deps are floor-pinned with no lockfile.
RESOLVED (deploy hardening): one root `railway.json` now carries build + deploy
(`/healthz`, ON_FAILURE) and `infra/railway.json` is gone; root `vercel.json`
deleted — frontend deploys on Vercel via dashboard (root=frontend), backend on
Railway; `pyproject-prod.toml` deleted; Dockerfile prod-extra fallback replaced
by a non-editable install with a non-root USER and a HEALTHCHECK.

## 3. HIGH — correctness, security, and product gaps (top 45)

### Security
- S1 `switch-tenant` mints tokens for disabled users and revokes tokens it doesn't own (`identity/service.py:234-253`).
- S2 Webchat session hijack: client-chosen `session_key` is the only visitor identity; response leaks `conversation_id` (`gateway/webchat.py:29-43`).
- S3 Cross-tenant idempotency-key collision: `webhook:{channel}:client_message_id` has no tenant scope → attacker can pre-register ids that silently drop victims' messages (`gateway/ingest.py:63-91`).
- S4 Unauthenticated AI-cost DoS: public webchat → embedding + full chat per message; 300/min spoofable; tenant's $50 budget exhausted (availability DoS) (`ai/hooks.py:90-105`, `gateway.py:29`).
- S5 No request body size limit anywhere (`main.py`) — unbounded JSONB writes + OOM.
- S6 SSRF: webhook-endpoint URLs unvalidated + signed internal payloads + error-text oracle (`platform/service.py:87-217`); same for `storage.persist_from_url` (`core/storage.py:61-71`).
- S7 No global uniqueness of channel identifiers; `resolve_tenant` scans all tenants' integrations first-match-wins → deliberate key squatting steals webhooks (`gateway/ingest.py:33-61`).
- S8 `security_events` inserts violate RLS WITH CHECK (nullable tenant + strict policy) → audit trail silently lost (`provision.py:65-83`, `platform/models.py:383-402`).
- S9 Access tokens never re-checked against DB (disabled users keep 30-min access; SSE streams bypass membership checks entirely) (`identity/deps.py:42-61`, `realtime/router.py:43-76`).
- S10 Webhook replay: static HMAC, no timestamp/nonce; status receipts have no dedupe and no state-machine validation (`whatsapp.py:51-60`, `conversations/router.py:260-279`).
- S11 IDOR in conversation assign (any user id; FK oracle) (`conversations/router.py:140-153`).
- S12 Enumerability: register 409 + login timing oracle (no dummy bcrypt) (`identity/service.py:73-138`).
- S13 Tokens in query strings on both SSE endpoints; no security headers middleware.
- S14 Staging runs with forgeable JWTs (`change-me` accepted unless environment=="production") (`config.py:69-78`).

### Reliability / concurrency
- R1 Outbox relay reclaims on `created_at` (row creation, not claim time) + one commit per batch → slow batch = guaranteed double-publish (`outbox.py:37-44,151`).
- R2 Retry republish is fire-and-forget `create_task` — lost on shutdown; entry already acked (`workers/base.py:159-164`). The docstring's own "not_before through the outbox" design is unimplemented.
- R3 `asyncio.gather` without return_exceptions + no signal handlers → one pool crash kills all pools, no graceful drain (`workers/run.py:33-45`).
- R4 AI lease/tx held across the entire model loop (up to ~50 min) → connection-pool exhaustion platform-wide (`message_worker.py:101-121` → `ai/runtime.py`).
- R5 Duplicate open conversations (no partial unique index); `unread_count += 1` read-modify-write; `mark_read` never marks messages (dead SELECT) (`conversations/service.py:36-55,127,267-274`).
- R6 Telegram `message_id` is per-chat → tenant-wide dedupe drops/cross-attributes messages; `edited_message` shares ids (`telegram.py:57`).
- R7 Delivery receipts overwrite any status without validation/ordering — out-of-order regressions (`conversations/router.py:260-279`).
- R8 Order transitions unlocked; concurrent cancel double-releases stock (theft of other orders' reservations) (`orders/service.py:332-372`).
- R9 `complete_transfer` double-apply; transfers ship reserved stock; no cancel; feature unreachable (`inventory/service.py:268-309`).
- R10 Refund over-refund race (no payment lock); refunds of non-captured payments (`orders/service.py:607-643`).
- R11 `reconcile_*` jobs: last-writer-wins vs phase-3; blind `failed` after 15 min; scheduler claim blocked by RLS and by no producers (`orders/service.py:545-580`, `scheduler_worker.py:92-104`).
- R12 Scheduler handler DB-error poisons the whole claim batch in a crash loop; no backoff (`scheduler_worker.py:126-141`).
- R13 `record_usage` upsert race → IntegrityError rolls back the whole AI run incl. the reply (`ai/usage.py:29-51`).
- R14 Platform workers consume `platform.events` which nothing publishes (notifications/webhooks/retries dead pipeline) (VERIFIED) (`platform_workers.py:24,55`).
- R15 WebhookWorker holds DB tx across 15s HTTP; endpoint-missing path loops forever without attempts increment (`platform_workers.py:67-88`).
- R16 Realtime cursor applied identically to all streams (replay/loss after reconnect) (`realtime/router.py:105-115`); `conversation.events` has no producer.

### Commerce correctness
- M1 No payments/refunds/cancel API (see C10); `reconcile_payment` can downgrade captured→failed and forge refunds without Refund rows (`orders/service.py:527-542`).
- M2 Blocked/merged/tombstoned customers can order; `get` ignores `deleted_at`/`merged_into` (`customers/service.py:40-52`).
- M3 Refunded money still counted as revenue (order stays `completed`; no partial_refunded status) (`analytics.py:22,127`).
- M4 Blocked/product-status unchecked at checkout (draft/archived sellable; AI too) (`orders/service.py:193`, `ai/tools.py:80-88`).
- M5 ROAS uses `campaign.budget` as spend; attribution double-books full value on first+last touch; conversions unreachable (no endpoint, no dedupe) (`marketing/analytics.py:164-202`, `marketing/service.py:218-235`).
- M6 `lifetime_value` never updated by any order path → segments on LTV always empty.
- M7 No discount/shipping/tax engine; `grand_total = subtotal` always; currency hardcoded EGP; `ProductPrice` tiers write-only (`orders/service.py:203-221`).
- M8 Order API missing: customer/number/date filters, payments list, status history, shipping update, shipments; `Shipment`/`ProductImage` dead tables.
- M9 `GET /inventory/movements` without variant returns [] (IS NULL on NOT NULL); movement `reason` free-text; no ledger rows for reserve/release (`inventory/router.py:39-42`).
- M10 Daily analytics bucket in UTC (merchant day shifted); `low_stock` counts zeroed balances (noise) (`analytics.py:136-152,251-260`).
- M11 `POST /orders` has no idempotency (double-click = two orders + double stock hold).
- M12 Phone/email identity resolution is exact-string, no E.164 normalization → duplicate customers.

### AI safety
- A1 Knowledge content concatenated verbatim into the system prompt, unbounded, threshold-less, no chunking, no dedupe, no delete endpoints; ingestion fails hard on provider error (row rolls back) (`ai/hooks.py:88-93`, `knowledge.py:34-95`).
- A2 Guardrails: 4 literal markers only; `margin` regex false positives; tool-evidence check unreachable; guardrail lives in hooks, not AgentRunner (any future caller bypasses it); no input-side guardrail (`guardrails.py:19-97`).
- A3 History mis-mapped: failed/unknown outbound and system messages replayed as assistant turns; current message duplicated in history; media-only messages invisible (`ai/runtime.py:319-335`).
- A4 Budget: agent_id dropped (per-agent budgets unreachable); warn/fallback unimplemented; no reserve/settle; input tokens uncosted; embeddings unmetered; cost rounds to $0.00 (Numeric(14,2)) → cap unenforceable (`gateway.py:97-137`, `model_kit.py:22`).
- A5 Platform-key fallback silently bills the deployment for tenant traffic; keys plaintext in JSONB; `AIProviderPolicy` dead → conversation PII egress ungoverned (`gateway.py:71-80`).
- A6 Auto-reply ignores conversation state: talks over humans in `waiting_human`/`closed`/pending-handover; agent = oldest-active tenant-wide (`hooks.py:63-105`).
- A7 Read-only tools not customer-scoped + unescaped LIKE + no per-conversation tool budget → competitor can enumerate catalog/stock via chatbot (`ai/tools.py:86-181`).
- A8 Model/agent params unvalidated (temperature ≤ 9.99, max_output_tokens negative → permanent provider 400s); provider `usage` trusted blindly (malformed usage discards a billed completion); retry re-sends identical payload without idempotency (double-billing) (`providers.py:121-134`, `runtime.py:266`).
- A9 `ai_sessions`, `Prompt`, `AIEvaluation`, memory governance — all dead; e2e_ai_test verdict hardcoded PASS.
- A10 Staff knowledge search locked to `customer_facing` (staff_only/internal unreachable); no ivfflat/HNSW index (exact scan) (VERIFIED no index anywhere).

### API contract
- P1 Invitation flow broken end-to-end: create on unregistered router, accept has no route; `users_router`/`tenants_router` dead (`identity/router.py:20-21,115`; grep-verified).
- P2 Billing-hosted notifications `POST /api/v1/notifications` 404s (platform_router not registered in main) (VERIFIED); two different notification contracts, one dead.
- P3 403 (not 401) on all auth failures; phantom 401 in OpenAPI; `{"detail": "not found"}` with HTTP 200 on notification read.
- P4 RBAC patchy vs seeded matrix: product create, inventory movements, customers read, conversation send/read, tasks, billing usage recording all ungated for staff.
- P5 Four error-body shapes (v2 envelope, FastAPI 422 default, `{"detail"}` legacy handler, rate-limit shape); no RequestValidationError handler; request_id header ≠ body request_id.
- P6 Middleware ordering: CORS inside rate-limit → 429s have no CORS headers; preflights consume the rate budget.
- P7 Pagination: two sort keys between page 1 and page N (customers, conversations); negative/unbounded `limit/offset/days` on 7 routers (LIMIT -1 → unlimited; offset<0 → 500).
- P8 Three list envelopes (bare array / {items,next_cursor} / unions) + ~45 of 62 routes untyped (no response_model) → OpenAPI useless.
- P9 Two SSE dialects; no Last-Event-ID; free-text status filters return silently-empty 200s.
- P10 No PATCH/ETag/If-Match anywhere despite version columns; no idempotency keys on client-facing POSTs; integrations upsert returns 201 on update.
- P11 Unreachable service surface: tags/notes, payment/refund/cancel, product update/archive, transfers, user management, leads list, webhook-endpoint list/delete.

### Frontend
- F1 (see C14) XSS + logout.
- F2 `getTokens()` JSON.parse without try/catch — one malformed byte bricks the whole dashboard (`lib/api.ts:13-17`).
- F3 Command palette fires `/search` in an infinite loop (mutate identity in effect deps) (`command-palette.tsx:114-122`).
- F4 `/accept?token=` route missing and link not copyable — invites unusable (`settings/page.tsx:119-126`).
- F5 Nested `FihristProvider` on 9 public pages → theme/lang toggles dead there (VERIFIED).
- F6 Bell SSE reconnect-per-render (inline streams array) + second unfiltered SSE + no refresh on token expiry (`use-realtime.ts`, `notifications-bell.tsx:70`).
- F7 Global search drops entity_id for 4/5 types; `?conversation=` ignored by inbox → Cmd+K is a dead end.
- F8 EN dictionary 85/214 keys — English mode renders Arabic; module-scope string captures force `window.location.reload()`.
- F9 No error boundary anywhere; 5+ pages render failures as "empty state" (inventory shows "no stock" on a 500).
- F10 Notifications dropdown + palette results keyboard-inaccessible (Radix menu with plain buttons; no listbox semantics); `<html lang>` never updates in EN mode.
- F11 No server pagination consumed; CustomerDrawer fetches ALL orders and filters client-side.
- F12 Thread header shows raw customer_id UUID; reply draft survives conversation switches (cross-thread send).
- F13 Dashboard chart timezone off-by-one; notification digits ar-EG default (٠١٢) vs Latin everywhere else.
- F14 `?new=1` never cleaned → dialogs reopen on refresh; workspace switcher is a fake placeholder.
- F15 Two font pipelines (blocking Google Fonts link + next/font); ~550 lines dead CSS shipped per route.

### Ops / data / quality
- O1 (see C11) migration chain + pgvector.
- O2 `segments` migration empty + model not in model_registry → table/RLS absent (VERIFIED).
- O3 Downgrade chain broken by ~145 unnamed constraints (Alembic's own warnings baked in).
- O4 CI runs ~67/178 tests (no postgres/redis services); §176 gate (12 tests) never runs in CI; `docker-publish` builds an image nothing deploys.
- O5 Tests execute against the REAL production Supabase DB (`conftest.py:3-8`).
- O6 No ESLint anywhere in frontend; no playwright job in CI; `npm install` (not ci).
- O7 provision.py rewrites `DATABASE_URL` silently, hardcodes project ref, brittle password parser (rotates password on format drift); deploy_railway rotates Redis password/JWT per deploy; CORS_ORIGINS="*" hardcoded for prod.
- O8 Verification theater: e2e_ai_test PASS hardcoded; rls_smoke_test false-PASS branch + crash on None DSN + orphaned users in prod.
- O9 n8n workflows don't implement the contract: bearer compare instead of HMAC; broken n8n expression (`Bearer {{...}}` without `=`); signature header references a field never emitted; re-serialized body can't match Meta's signed bytes; workflows ship inactive.
- O10 No /metrics, no OTel, worker logs lack correlation ids; no staging, no backup/restore automation, alerts documented with zero backing config; PII map omits model_configs keys, integrations.credentials, security_events, webhook payloads.
- O11 No HNSW/ivfflat index on embeddings (exact scan, verified); seed_demo plants `demo@…/Demo-1234` in the production DB.
- O12 Stray root packages `app/`+`tests/` shadowing backend; ruff excludes hand-written migrations.

## 4. Dead infrastructure inventory (built, migrated, never wired)

| Item | Location | Status |
|---|---|---|
| EntitlementService | billing/service.py:140-177 | zero callers |
| ScheduledJob producers | platform/models.py:305 | nothing inserts jobs; scheduler claims nothing (RLS + no producers) |
| RetentionWorker | workers/retention_worker.py | not in POOLS; nothing emits `retention.run` |
| WebhookEvent ingress | platform/models.py:221 | never written by real ingress |
| InboundMessageDedupe (§142) | platform/models.py:358 | dead (ingest uses IdempotencyKey) |
| DeliveryAttempt | platform/models.py:332 | dead |
| Automation (platform) + Workflow execution | automation/service.py | no dispatcher, no router, not in main.py |
| Privacy DSR + DeletionService | privacy/service.py | no router, unreachable |
| SegmentService | segments/service.py | no table, no registry entry, unreachable |
| IdentityMergeService | customers/service.py:308-526 | no API surface |
| add_memory/search_memory + Memory governance fields | ai/knowledge.py | **wired 2026-09-23 (§158)** — recall in `ai/runtime.py` (own untrusted context turn) + staff CRUD in `ai/router.py` `/ai/memories*`; provenance columns migrated (`e5b8d2f0a1c3`) |
| AIProviderPolicy | ai/models.py + ai/policy.py | **wired 2026-09-23 (§43)** — `decide()` ladder enforced on `gateway.chat` and `gateway.embed`, admin upsert route; residency/retention migrated (`f6c9e3a1b5d8`) |
| AIEvaluation | ai/models.py + ai/evaluation.py | **wired** — canary/rollback flow called from `ai/router.py:530` |
| Prompt (§38 prompt registry) | ai/models.py:79 | dead schema — zero references outside the model |
| ai_sessions | conversations/models.py:206 | dead schema — zero references outside the model |
| voice STT/TTS | conversations/voice.py | **STT wired 2026-09-23 (§35)** — `transcribe_inbound_voice` (`workers/message_worker.py`) under the conversation lease, budget reserved before the provider call, transcript persisted on `attachments.transcript_text`; **TTS still dead** — `synthesize`/`OpenAITTSProvider`/`get_default_tts_provider` have no caller (auto voice reply is an open product decision). Related delivery gap: `MessageWorker._deliver_one` never passes `media_type`, so an outbound audio message would deliver as `image` |
| Circuit breaker | core/circuit_breaker.py | zero importers |
| ObjectStorage in ingest | core/storage.py | zero callers (provider URLs stored raw) |
| MessageTemplate / TemplateApproval | conversations/models.py | stored, never checked at send |
| Consents | privacy/models.py | never enforced in messaging |
| SLAPolicy / BusinessCalendar / SLAEvent | operations/models.py | no clock, no writer, no worker |
| Shipment / ProductImage / ProductPrice / invoices lines | orders, catalog | dead or write-only |
| FeatureFlag / MetricDefinition / SecretReference | platform/models.py | dead tables |
| InboxQuery read model (§137) | — | absent (joins in write service) |
| Outbox `not_before` scheduling | workers/base.py docstring | unimplemented |
| NotificationPort / PaymentProviderPort / SecretStorePort | — | absent (SMTP stub derefs nonexistent setting) |

## 5. Missing product/API surface (dashboard cannot run the business)

- Invitations accept; user management (list/patch/deactivate); roles/permissions list.
- Customer PATCH/block/archive, tags, notes endpoints; customer record page (360 tabs/timeline).
- Product GET/PATCH/archive, variants management, warehouses list, transfers.
- Order: payments create, refunds, cancel, customer/number/date filters, payments+history detail, shipping update.
- Conversation detail/update; Inbox views + context tabs; saved views; My Work; global health.
- Webchat visitor read surface (staff-only today — visitors can post, never receive).
- Jobs API (GET/retry/cancel); approvals UI + decide endpoint; platform-admin plane.

## 6. Spec compliance snapshot

§177 non-negotiable rules: 14 PASS · 11 PARTIAL · 5 FAIL (FAIL: rule 11 module
boundaries, rule 21 provider event ordering, rule 24 entitlement enforcement, rule 28
external SoT policies, rule 29 tenant-scoped restore).
§176 pre-production gate: 9/23 scenarios pass; 13 missing (out-of-order events,
stale-run cancellation, tool-scope attack, n8n outage, Redis replay, DLQ replay, payment
UNKNOWN, oversell concurrency, tenant restore, noisy neighbor, realtime resync, schema
compat, duplicate tool call).

## 7. Theme of the audit

1. Everything "runs" in the happy path; almost nothing survives failure, concurrency,
   or an attacker.
2. Governance was built as schema (policies, approvals, budgets, flags, entitlements)
   and never connected to behavior — governance-by-docstring.
3. The migration/deploy chain cannot reproduce the environment that the docs describe.
4. The frontend consumes roughly the first page of everything and cannot run invites,
   search navigation, multi-tenancy, or the merchant commerce loop.

## 8. Proposed build order (each phase = shippable, tested increment)

Phase A — Stop the bleeding (security + deployability, ~1 week):
1. C1 SSE meta fix + fail-closed tenant + cursor clamp. 2. C2/C7 webchat: remove from
webhook registry, single validated ingest schema, server-issued session tokens. 3. C13
rate-limit prefixes + trusted IP + atomic counters. 4. C11/O1/O2/O3 migration chain,
pgvector image+extension, segments, downgrade names. 5. C12 RLS DDL into migrations +
bind GUCs in public/auth paths + CI job with services + rls smoke in CI. 6. C14/F1/F2
frontend XSS, logout, parse guard. 7. C15 deploy topology: one railway.json, lock deps,
fix preDeploy DSN, delete vercel.json or fix it.

Phase B — Correctness of the core loop (messaging + commerce):
8. C3/C4/C5/C6/R1/R2 worker semantics: atomic claim, outbox-row dedupe key, failed-row
reclaim + attempts reset, XAUTOCLAIM, durable not_before, per-row commit. 9. C7/R5/R6/R7
messaging: re-raise ConversationBusy, atomic unread, partial unique conversation index,
Telegram chat-scoped dedupe, receipt state machine. 10. C9/C10/M1 commerce: payments
create/refund/cancel endpoints, convert decrements reserved, expiry worker, guards +
locks + restock. 11. R13/R14/C8/R11: ai_usage upsert, stream-name fix, approval column +
decide/resume endpoints, reconcile correctness.

Phase C — AI governance for real: 12. A1/A2/A3 (chunking, thresholds, input guardrail,
history mapping, guardrail into AgentRunner). 13. A4/A5 (reserve/settle, per-model
pricing Numeric(18,8) or micro-USD, per-tenant key requirement or explicit platform-pays
flag, provider policy enforcement). 14. A6/A7 (state-aware auto-reply, customer-scoped
tools, tool budget).

Phase D — API/product surface: P1/P2/P4/P7/P8/P10 + §5 missing endpoints + frontend
F3-F15 (priority: search navigation, /accept, i18n completion, error states, SSE client
merge).

Phase E — Wire the dead infrastructure + spec gap closure (Phase 5-8 of the build plan):
entitlements into flows, scheduler producers + retention worker into POOLS, webhook
ingress durability, media pipeline, messaging policy layer (24h window + consent),
metering pipeline, platform-admin plane, tenant lifecycle.

Every phase keeps the existing golden rules: outbox-first, RLS double-enforcement,
worker taxonomy, error contract v2.
