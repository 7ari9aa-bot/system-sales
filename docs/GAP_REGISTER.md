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
Wave 4 (2026-09-23/24) worked this list end to end. Case counts below are
`pytest --collect-only` counts for the named file; the DB-backed half of each
skips locally without `DATABASE_URL_APP_ADMIN` (`tests/conftest.py:52`), so a
local count is not a claim that the database cases ran.
- M1 ~~No payments/refunds/cancel API (see C10); `reconcile_payment` can downgrade captured→failed and forge refunds without Refund rows (`orders/service.py:527-542`)~~ — closed in W4: `POST /orders/{id}/payments`, `POST /orders/{id}/payments/{payment_id}/refunds`, `POST /orders/{id}/cancel` (`orders/router.py:211,236,260`), and `Refund(` is now constructed in exactly one place in `app/` (`orders/service.py:1102`, inside `register_refund`) — the refund ledger, not a status word, is the source of truth (ADR-054). `tests/test_order_refund_ledger.py` (8), `tests/test_partial_refund_status.py` (14).
- M2 ~~Blocked/merged/tombstoned customers can order~~ — checkout refused all three since Wave 0 (`orders/service.py:276-291`); closed in W4 for everyone else: `CustomerService.get` (`customers/service.py:82-103`) raises NotFound on a `deleted_at` row and Conflict — carrying `merged_into_customer_id` — on a merged one, so every caller inherits the guard the order path used to hand-roll; `get_by_identity` refuses tombstones through that same door (`435-437`) and `_resolve_live_by_contact` drops dead rows before matching (`439-462`). The one deliberate reader of a tombstone is `get_for_erasure()` (`105-118`), and its only caller is the erasure pipeline (`privacy/service.py:39`). `tests/test_customer_identity_resolution.py` (25), `tests/test_privacy_erasure.py` (2).
- M3 ~~Refunded money still counted as revenue (order stays `completed`; no partial_refunded status)~~ — closed in W4 (ADR-054), and `partial_refunded` was deliberately NOT added: refund state is derived from the ledger (`orders/money.py:150` `refund_state()` → `none|partial|full`, `REFUND_STATES` at `102`), reported on `GET /orders/{id}` (`router.py:94`) and stored nowhere. Revenue reads net: `analytics/service.py::net_of()` (`92-105`, floored at zero with the overshoot surfaced as `refund_excess`), and the status filters behind `revenue`/`net_revenue`/`refunded_amount`/`aov` are rendered from `MetricRegistry`'s own definitions (`_status_sql`, `45-62`) instead of a second hand-written WHERE clause. `tests/test_analytics_correctness.py` (26), `tests/test_order_refund_ledger.py` (8).
- M4 ~~Blocked/product-status unchecked at checkout (draft/archived sellable; AI too)~~ — closed in W4 on the sell path: `SELLABLE_PRODUCT_STATUSES = frozenset({"active"})` (`orders/service.py:71`) is enforced by `sellable_refusal()` (`174`) before a single unit is reserved (`create_order`, `499-510`), and the AI order tool calls the same `OrderService.create_order` (`ai/tools.py:300`), so a draft product cannot be bought from chat either. Still open in this line: the AI *browse* tool filters `ProductVariant.is_active` but not `Product.status` (`ai/tools.py:170-184`), so an unlisted product stays enumerable — unsellable, but visible. `tests/test_checkout_rules.py` (6).
- M5 ~~ROAS uses `campaign.budget` as spend; attribution double-books full value on first+last touch; conversions unreachable (no endpoint, no dedupe)~~ — closed in W4: `POST /marketing/conversions` (`marketing/router.py:193`) and `GET /marketing/campaigns/{id}/conversions` (`220`), deduped by the database rather than by code — `record_conversion` takes a savepoint and maps `IntegrityError` to either `ConflictError` or the existing row flagged `idempotent=True` (`marketing/service.py:161-227`, keys `uq_conversions_tenant_order_type` + `uq_attributions_credit`, migration `c9f2a6b1d4e8`). ROAS now names its own denominator (`BASIS_PLANNED_BUDGET` / `BASIS_ACTUAL_SPEND`, `marketing/analytics.py:30-31`), `campaign_actual_spend()` returns `{}` on purpose because no provider-cost ingest exists (`275-286`), `_ratio()` answers `None` on an empty denominator instead of dividing by zero (`242-244`), and first+last touch are documented as two VIEWS of one order with rollups filtering to one model (`marketing/service.py:7-15`). Still open: the actual-spend basis stays empty until a provider cost feed lands, which is an external integration and not a gap in this repo. The money that does exist crosses as text — `analytics.wire_money()` covers the read models (`f630e68`) and `attribution_report()`'s credited revenue stopped going through `float()` (`25f8857`). `tests/test_marketing_conversions_api.py` (7), `tests/test_roas.py` (7), `tests/test_marketing_read_models.py` (15).
- M6 ~~`lifetime_value` never updated by any order path → segments on LTV always empty~~ — closed in W4: `_recompute_lifetime_value()` (`orders/service.py:1460-1517`) is one derived SQL UPDATE off the payment/refund ledger, floored with `GREATEST(…,0)` and written in raw SQL so `orders` never imports `customers`; every money event calls it — `add_payment` (`922`), `reconcile_payment` (`999`), `register_refund` (`1129`). `tests/test_customer_lifetime_value.py` (17).
- M7 ~~No discount/shipping/tax engine; `grand_total = subtotal` always; currency hardcoded EGP; `ProductPrice` tiers write-only~~ — closed in W4-T3 (ADR-053): `tenants.currency` + `orders/money.compute_totals` (`grand_total = subtotal − discount + shipping + tax`, components accepted on `POST /orders`), the ladder read at checkout via `CatalogService.price_for` (highest applicable tier, order's currency), and every money write path takes the tenant's currency or is refused (`core/currency.py` = the ISO exponent table; `amount_minor`/`from_amount_minor` at the provider boundary; `PUT /api/v1/tenants/{id}/currency`, audited). `core/money.py` deleted. `tests/test_tenant_currency.py`. Still open in this line: only §47's cross-currency rate reporting, and that is unmet *by design* (one currency per tenant). The frontend half closed with the order dialog — `discount_total`/`shipping_total`/`tax_total` are typed in the money field and sent as 2-decimal strings, parsed on BigInt minor units so the estimate on screen is not float math (`frontend/src/components/orders/`, `frontend/e2e/order-money.spec.ts`).
- M8 ~~Order API missing: customer/number/date filters, payments list, status history, shipping update.~~ ~~shipments; `Shipment`/`ProductImage` dead tables~~ — closed in W4-T1/T2: `POST/GET /orders/{id}/shipments` + `POST /shipments/{id}/status` (one write path that moves the order through `TRANSITIONS`, ADR-051) and `POST/GET /products/{id}/images`; `tests/test_order_fulfillment.py`, `tests/test_catalog_admin_surface.py`. ~~a returned parcel went nowhere~~ — closed in W4-T2b: `returned`/`failed` now run the `order_return` saga (restock per reservation state → close the order, with the undo each step is owed) and `POST /orders/{id}/return` is the staff entry (ADR-052, `tests/test_return_saga.py`). ~~customer/number/date filters, payments list, status history, shipping update~~ — the rest of the row closed in W4: `GET /orders` takes `customer_id`/`number`/`created_from`/`created_to` (`orders/router.py:37-55`), `GET /orders/{id}/payments` (`197`) and `/status-history` (`204`) answer, `GET /orders/{id}` returns the money position with an ETag (`77-108`), and `PATCH /orders/{order_id}/shipping` (`340-367`, `orders:write`, If-Match) is a versioned write that audits AND publishes — see ADR-055, which exists because the first version of it only audited. `tests/test_order_reads.py` (22), `tests/test_order_shipping_event.py` (8).
- M9 ~~`GET /inventory/movements` without variant returns [] (IS NULL on NOT NULL)~~ — fixed in W4-T1 (`None` now means "no filter", `tests/test_inventory_service.py`); ~~still open: movement `reason` is free-text, and reserve/release write no ledger row~~ — closed in W4: the reason vocabulary is two frozen sets (`inventory/service.py:44-62`, physical vs availability-affecting) with direction and reference checked before any session is touched (`check_movement_shape()`, `93-118`), `move()` refuses `hold`/`release` (`150-154`) and the router refuses an availability reason on `POST` while `?reason=` is pattern-matched so a typo is a 422 instead of a silent empty 200. Reservations are ledger-backed now: `reserve()` writes a `hold`/`reservation` row and links it (`227-268`, `InventoryReservation.hold_movement_id`, `inventory/models.py:150`, migration `c4f7a9b1d3e5`), `release()` records only what it actually frees and writes nothing when that is zero (`270-304`), `convert()` writes the paired `release` + `out`/`sale` (`829-890`), and `GET /inventory/movements?reservation_id=` walks the pair. Known limit, stated in the code: a release is attributed FIFO to the holds it frees and writes one reference row, so one release covering two holds names only one. `tests/test_inventory_movement_contract.py` (35), `tests/test_inventory_reservation_ledger.py` (12).
- M10 ~~Daily analytics bucket in UTC (merchant day shifted); `low_stock` counts zeroed balances (noise)~~ — closed in W4: buckets are cut on the merchant's calendar day, not UTC (`AT TIME ZONE CAST(:tz AS text)` over `paid_at`/`COALESCE(processed_at, created_at)`/placed-at, `analytics/service.py:283-362`, timezone resolved once in `analytics/timekit.py`), the revenue summary reports which timezone it bucketed by (`revenue_summary`, `238-268`), and the two stock bands are disjoint: `out_of_stock` is `available <= 0`, `low_stock` is `1..threshold` (`stock_health`, `365-403`). `tests/test_analytics_correctness.py` (26), `tests/test_marketing_read_models.py` (15). Still open: nothing on the zone — §47/M10 remainder gave each tenant its own `tenants.timezone` (migration `e3b7d2a9c4f1`, resolution order caller → tenant → deployment → UTC, reported as `timezone_source`), which is what this line said needed approving.
- M11 ~~`POST /orders` has no idempotency~~ — `/api/v1/orders` is on `IDEMPOTENT_PATHS` (`core/idempotency.py:115-120`) and `tests/test_order_idempotency.py` proves replay-once / reuse-with-a-different-body-409. What was left is the other half of the pair — **no client sent the header** — and it closed with the order dialog: one key per dialog OPEN, re-sent unchanged on a retry and across a 401→refresh, cleared on success, and NEVER re-minted after a 409 (a new key can create the order twice). `frontend/e2e/order-money.spec.ts` drives it in a browser; `ApiError` keeps the status so a 409 and a 400 can be told apart at all.
- M12 ~~Phone/email identity resolution is exact-string, no E.164 normalization → duplicate customers~~ — closed in W4 (ADR-056): one stdlib-only normalizer owns the rules (`core/contact_norm.py`: Egypt `+20` default with the legacy `+964` fabrication named as its own state, five phone states, `phone_candidates`/`email_candidates`, `legacy_fabrication`, `classify_stored_phone`, `find_canonical_collisions`), matching at write time goes through the candidates (`customers/service.py:268-287`, `_resolve_live_by_contact` `439-462`) so a stored local format still finds its customer, and tombstoned/merged rows are refused rather than matched (`82-103`). Existing rows were touched by a data-only migration (`d5a1c7e94b02`) that **marks** what it cannot safely rewrite under `extra → data_quality → m12_contact_backfill` and leaves `updated_at`, `version` and `customer_identities.external_id` alone; `GET /customers/contact-data-issues` (`customers/router.py:85-110`, `customers:write`, PII-redacted) reads the marks back. `tests/test_contact_backfill.py` (28), `tests/test_customer_identity_resolution.py` (25). Still open: the quarantine is not self-healing, by decision — ADR-056 §6 gives the operator a resolve route (`POST /customers/{id}/contact-issue/resolve`, `f4e4866`) for the marks a rule cannot settle, and refuses to merge two customers from it, because a merge retargets orders, conversations and ledgers and tombstones a row.

### Wave 4 close-out — read from code, then overtaken by the same wave (2026-09-24)
This list was written by reading finished code rather than the plan, which is the
only way to write one. Wave 4 then kept going, so each line below is now marked
with what actually stands.

Closed by the work that landed after this list was written:
- ~~**`metric_definitions` is never seeded.**~~ — `seed_definitions` is now a
  CONVERGE (`ON CONFLICT DO UPDATE` over the fields the registry owns, so a
  bumped definition reaches a live tenant instead of being skipped forever), is
  called from tenant bootstrap, and has
  `scripts/backfill_metric_definitions.py` for tenants that already exist.
  `tests/test_metric_definitions_seed.py` holds it. The in-code `MetricRegistry`
  remains the authority; the table is its tenant-visible audit copy.
- ~~**No per-tenant timezone.**~~ — migration `e3b7d2a9c4f1` adds
  `tenants.timezone` (nullable, no backfill: NULL is the tenant's own answer,
  "no opinion"), `timekit.resolve_timezone` walks caller → tenant → deployment →
  UTC and reports which layer answered, and `PUT/GET
  /tenants/{id}/timezone` refuses an unresolvable zone the way §47 refuses an
  unknown currency. `tests/test_tenant_timezone.py`.
- ~~**The reservation expiry sweep has no job.**~~ — `RECURRING_JOBS` carries
  `expire_reservations` and `ensure_recurring_jobs` seeds it from
  `SchedulerWorker.run`; `tests/test_reservation_expiry_sweep_wired.py` pins the
  call path statically AND drives the claim loop end to end, because a handler
  that nothing schedules is this repo's oldest failure mode.
- ~~**`archive_old_rows` is dead.**~~ — deleted, with the reason recorded in
  `analytics/service.py`: wiring retention needs a partition DDL that does not
  exist, so a partial wire would delete rows on a schedule nobody chose. The DDL
  landed in `546f109`, so the choice could be made — see §55–57 below.
- ~~`float()` at the marketing wire~~ — closed: `analytics.wire_money()` returns
  a cent-quantised string and every money figure on the marketing read models
  crosses as text (`None` stays `None`, not `"0.00"`). `CampaignRequest.budget`
  still accepts a number on the write side by design, and `_ratio()` is a ratio.

Still open, as re-measured today:
- **The address a staffer is told to correct is not on the screen that corrects it.** `PATCH /orders/{id}/shipping`
  replaces `shipping_address` whole (ADR-055 §5 — a merge cannot express "this line is gone"), but
  `GET /orders/{id}` does not return that column, so the dialog opens empty and a merchant fixing one
  line cannot see the three lines the submit will overwrite. The write is safe (versioned, audited,
  published); the READ is the gap, and it is a read-surface gap, not a dishonest screen.
- **The quarantine is drained by hand, one mark at a time.** `POST /customers/{id}/contact-issue/resolve`
  (`f4e4866`) lets an operator clear a mark they have decided, and it refuses a merge on purpose —
  but the Iraq-default rows still hold their wrong `phone` until a person supplies the real number,
  and a collided pair stays two customers until someone uses `POST /customers/merge`. Nothing
  auto-heals either, and nothing should: both are identity decisions.

Closed since the register was written (each had a red test first):
- ~~**The catalog CSV importer has no caller.**~~ — `POST /imports/customers` and
  `POST /imports/products` (`e9d60b7`) reach it through `CustomerService.create_from_import`, which
  applies the same normalizer and live-contact resolution a form applies, so a CSV cannot create the
  duplicate a form would refuse. The import paid for its own reach: the two cross-module edges it
  needed moved the audit writer to `app/core/audit.py` and took the ratchet from 97 to 94.
- ~~**§55–57 retention has no partition DDL.**~~ — `ai_usage` is RANGE-partitioned on `period_date`
  with a DEFAULT partition, `core/partitioning` maintains the horizon, and a month drops only after a
  tenant chose a policy (`546f109`); the policy finally has a door to be chosen from (`cab9795`); and
  the row stores the worker already purges — `messages`, `webhook_events` — are choosable through the
  same gate rather than a second allowlist (`edd5d46`).
- ~~**M12's quarantine awaits an operator.**~~ — the resolve half landed (`f4e4866`); see the two
  remaining lines above for what it deliberately does not do.
- ~~**`float()` survives at the AI tool edge.**~~ — `ai/tools.py` quotes a price as text and the
  browse tool can no longer enumerate what checkout would refuse (`b85cf84`).
- ~~**`float()` survives on the AI and CRM money paths.**~~ — all four sites now quote money as
  text: `ai/gateway.py:431,498` answer a budget check with `str(spend)`/`str(cap)` (the same pair
  its error path at `:490` had always shipped, so the two branches no longer disagree about type),
  `ai/router.py:121` reports a usage day's `cost` as a string and `:131` answers the period total
  as an exact `Decimal` sum the route — not the browser — computes (§55), `customers/service.py:1362`
  puts `lifetime_value` in the customer-context payload as the string `customers/router.py:49`
  already sent, and `workers/message_worker.py:144` hands `record_usage` the `Decimal` itself
  instead of the `float(cost)` that rounded away the sub-cent places `AI_COST` exists to hold.
  Proven by `tests/test_ai_money_wire.py`, `tests/test_customer_money_wire.py` and
  `tests/test_ai_usage_totals.py` (the last pins a `9999999999.12345680` probe that float64 cannot
  survive). Two `float()` calls remain in those files and neither is money: `gateway.py:486` is a
  percentage of a budget computed from Decimals first, and `router.py:188` is a memory
  `confidence` — the §47 rule keeps ratios and counts as numbers.

### The three live defects review found in Wave 5's parallel lanes (2026-09-24)
Landed work from four concurrent agents, read against what it claims. None of
these was caught by a test that already existed; each now has one that fails
without the fix.

1. **A §146 field guard on the read, missing on the write of the same column** (`af5428c`).
   `GET /orders/{id}` redacts `shipping_address` without `pii:read`; the
   `PATCH /orders/{id}/shipping` echo returned it raw. `staff` holds
   `orders:write` and not `pii:read` (`scripts/provision.py:250-261`), so the
   guard was bypassable by writing the record and reading the response. Both
   paths now go through `_redact_order_pii`, pinned DB-free in
   `tests/test_order_reads.py`.
2. **`Query(...)` used as a Python default is not a value** (`09f89ad`).
   `async def h(days: int = Query(default=30))` leaves a pydantic `FieldInfo` in
   the function's `__defaults__`. FastAPI replaces it over HTTP, so the route
   looked fine forever — while any in-process caller forwarded the declaration
   object into a SQL bind (`DataError: invalid input for query argument $1`).
   Analytics had it and CI run 35959902953 proved the cost; measuring the rest of
   the app found **38 more sites across 9 routers** (ai 8, marketing 6,
   operations 5, conversations 4, customers 4, platform 4, privacy 3, automation
   2, orders 2), all now declared `Annotated[type, Query(...)] = <value>`.
   `tests/test_route_parameter_declarations.py` walks every endpoint reachable
   from `create_app()` and refuses any parameter whose default is a `FieldInfo`,
   so the count cannot climb again; `tests/test_analytics_overview.py` calls one
   converted route with zero arguments as the live proof.
3. **`GET /platform/admin/tenants/{tenant_id}` answered 500 for every tenant** (`4dcb7a9`). It counted
   outbox backlog with `OutboxEvent.tenant_id == tenant_id`, a column the model
   does not have — §19 put tenancy in the event envelope instead, so the
   attribute lookup raised `AttributeError` inside the request. The predicate now
   reads `meta->>'tenant_id'` (the same key the relay refuses to publish
   without), and `tests/test_tenant_health_outbox.py` compiles each statement and
   rejects any column `outbox_events` lacks, which is the judgement Postgres makes.

### Three more defects review found in the same reading
Found by reading finished work against the behaviour it claims — none of them by
a red test that already existed. Each now has one.

1. **`GET /analytics/daily-series` labelled the wrong zone.** The route resolved
   the timezone chain itself — before it had looked at `tenants.timezone` — and
   printed that answer as the response's `timezone`, while the service re-resolved
   correctly and cut the buckets in the tenant's zone. A Cairo shop got Cairo
   days under a deployment label. Fixed by resolving once through
   `resolve_report_timezone` and reporting `timezone_source` like every other
   reader; watched RED (`America/New_York != Africa/Cairo`).
2. **`tryRefresh` asked for `/api/v1/api/v1/auth/refresh`.** The client had three
   copies of the base-URL rule; the two that appended the prefix unconditionally
   were wrong under the same-origin deployment `vercel.json` rewrites describe. A
   404 there reads as "session gone", so the first expired token logged the user
   out — and the logout ping and the SSE default (`http://localhost:8000`) had
   the same class of defect. `apiUrl()` is the only builder now, and
   `frontend/scripts/check-request-urls.mjs` loads the real compiled module and
   calls it under both shapes rather than trusting a grep.
3. **A workflow failure raised a 5xx, and a double restore double-reported.**
   `WorkflowService` wrote its `WorkflowFailure` row without `tenant_id`, which
   is NOT NULL under FORCE RLS — the failure path itself rolled back the
   execution the router docstring promised was never a 5xx.
   `TenantRestoreService.execute_restore` read its job without `FOR UPDATE`, so
   two concurrent Executes both passed the `restoring` guard, both emitted
   `tenant.restore.completed`, and the loser reported `restored: 0` for work that
   had happened. Both are §176 gate scenarios now
   (`test_gate_n8n_outage.py`, `test_gate_tenant_restore.py`).

### The two defects review found in Wave 4, and what each left behind
Both were found by reading the finished wave against the code it was meant to
complete, not by a red test. Each now has a regression test that names it.

1. **The return saga's compensation restored the shelf but not the §140 row.**
   `execute` released an unpaid order's hold *and* cancelled its durable
   `InventoryReservation` (`orders/returns.py:139-141`); `compensate` put the
   hold back with `InventoryService.reserve()` — quantity, warehouse and
   balance all correct, and no reservation row behind it. A retried return then
   read that order as never having held anything, and restocked units it had
   never sold. Fixed by recreating the durable row inside the same compensation
   (`returns.py:172-195`, `create_reservation` under `_RESERVATION_TTL`), so the
   undo gives back exactly what `execute` took. Regression:
   `tests/test_return_saga.py::test_an_undone_release_restores_the_reservation_it_released`
   (`:488`); its sibling `test_when_the_close_step_fails_the_restock_is_undone`
   (`:450`) holds the other half of the pair. Recorded in ADR-052.
2. **`PATCH /orders/{id}/shipping` was silent.** The route wrote the row and an
   `audit_logs` line and published nothing. The reason the omission stayed
   invisible is the interesting part: `order.shipping_updated` was not in
   `core/events/schemas.py`'s `DOMAIN_EVENT_TYPES`, so `build_envelope` would
   have refused the write — but no call site ever reached the refusal, because
   no call site existed. Fixed on both sides: the event type is declared
   (`schemas.py:142`), `update_shipping` stages it in the same transaction as
   the versioned update carrying the row's real `aggregate_version`
   (`orders/service.py:1310-1409`), and it is charged `CRITICAL_SYSTEM` (rank 3)
   so a tenant flooding its own stream cannot delay a corrected address
   (`core/fairness.py:68,112`). A no-op patch returns the order unchanged and
   bumps nothing — no version, no audit row, no event. Regression:
   `tests/test_order_shipping_event.py` (8 cases, 5 DB-backed), with
   `tests/test_event_aggregate_version.py` holding the version rule. Recorded in
   ADR-055.

### Measured open hazard (2026-09-24): the ADR-058 claim holds a pooled connection across the whole effect
Not a defect that fired — a capacity invariant nobody stated. Measured from code, no
fix applied, and the fix is an owner decision (§7) because it moves production
connection counts.

`StreamWorker._process_event` (`workers/base.py:258`) opens the inbox claim
transaction through `_claim_inbox` (`:313-349`: `SessionLocal()` + `BEGIN` +
`pg_try_advisory_xact_lock`) and returns with it **open**; `_close_inbox` runs only in
the caller's `finally` (`:304-308`), after `handle()` has completed. ADR-058 chose that
shape on purpose —
the commit that writes the `processed_events` marker is the commit that releases the
lock, so there is no window for a concurrent redelivery to re-run the effect. The cost
is that the claim connection is checked out for the entire duration of the effect, and
**every** handler opens its own session while that happens
(`message_worker.py:204,260,289`, `campaign_worker.py:154`, `job_runner.py:342,348,356`):
**two connections per in-flight event, minimum**.

The arithmetic, on what the code actually does today: `app/workers/run.py:64-74` runs
the outbox relay plus every pool in `POOLS` (messages, notifications, webhooks,
campaigns, scheduler, jobs = 6) as `asyncio.gather` tasks **in one process**, on the
one process-wide engine — which `app/core/db.py:52-56` builds with **no pool
parameters**, so it carries SQLAlchemy's defaults: `pool_size=5`, `max_overflow=10`,
15 connections, `pool_timeout=30`. Each worker consumes one event at a time
(`run()` awaits `_process` in its loop), so six busy pools hold 6 claims + 6 handler
sessions = **12**; the relay in the same process opens a session per claimed row
(`core/events/outbox.py:477`) for **13**; and one event being retried takes the pool to
**14 against 15**, because `_republish_after` opens its own `SessionLocal()`
(`workers/base.py:508`) to stage the retry while the claim transaction that owns the
attempt is still open. It fits. By one unit.

Three changes each break it silently, and none of them looks database-related from its
diff: any handler that nests a second `SessionLocal()` of its own (the retry staging
path above already does, and the arithmetic is one unit from the ceiling), a second
pool added to `POOLS`, or any per-pool concurrency to raise throughput. Then the pool
is fully checked out by claim transactions that each wait on a connection their own
handler needs — the holder cannot release, the waiter cannot start, and 30 seconds
later every affected event fails with `TimeoutError` from the pool, not from Postgres.

The two honest resolutions, both owner-sized: state the pool from config with the
invariant in the comment (`pool_size + max_overflow ≥ 2 × (len(POOLS) + 1) +
headroom`), which is a knob change and needs the real `max_connections` of the Supabase
pooler; or bound concurrent claims with a process-wide semaphore sized from the pool,
which costs throughput but no configuration. A test can pin either: the count of
`POOLS`, the engine's pool limits, and the two-connections-per-event shape are all
readable without a database.

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
| Automation (platform) + Workflow execution | automation/service.py | **stale as written; the real gap is narrower and worse** (measured 2026-09-24) — there IS a router and it IS in `main.py` (`automation/router.py`, 8 routes; imported at `main.py:40`, mounted at `:271`), covering CRUD, publish, status, list and `POST /workflows/executions/{id}/run`. What is missing is the **trigger**: `WorkflowService.execute_for_event` (`service.py:132`) is the only code in the repo that inserts a `WorkflowExecution`, and it has zero production callers — its only caller anywhere is `tests/gate/test_gate_n8n_outage.py:76`. So `workflow_executions` stays empty in a running system and the `/run` route can only answer 404. The separate `automations` table (`platform/models.py:278`) is genuinely unread and unwritten — superseded by these `workflows` tables |
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
| ProductPrice / invoices lines | catalog, billing | write-only (tier fields now writable via `POST /variants/{id}/prices`; still no reader in pricing logic) |
| FeatureFlag / MetricDefinition / SecretReference | platform/models.py | **measured 2026-09-24: two of three were stale, the third is now closed** — `FeatureFlag` (`GET/POST /platform/flags*`) and `SecretReference` (register/rotate under `settings:write`) were already served by live routes. `metric_definitions` was the real case, and not "dead": WRITE-ONLY (provisioning seed + `scripts/backfill_metric_definitions.py`, read only by the writer's own convergence SELECT), while both endpoints named "definitions" answered from the in-code `MetricRegistry`. Closed by `GET /platform/metrics/definitions` (table-backed, reports `missing`/`drifted`), pinned by `tests/test_contract_reachability.py` §6, which now also baselines every table `app/` never reads |
| InboxQuery read model (§137) | conversations/inbox.py:79 | **closed 2026-09-24 (`b337ae5`)** — `InboxQuery.page()` answers `GET /api/v1/inbox` (`router.py:149`, mounted without a `/conversations` prefix) in one statement: conversation + customer + last message + assignment + unread + `sla_status`/`sla_deadline_at`, with §99's `unassigned`/assignee/status/channel/customer views as SQL predicates and a keyset cursor. The write service no longer carries those joins |
| Outbox `not_before` scheduling | workers/base.py docstring | unimplemented |
| NotificationPort / PaymentProviderPort / SecretStorePort | — | absent (SMTP stub derefs nonexistent setting) |

## 5. Missing product/API surface (dashboard cannot run the business)

Re-measured 2026-09-24 against the running OpenAPI document (199 paths, 244 path+method operations), not against this list's memory of it. Most of what this section used to call missing has an endpoint now; the honest remainder is short, so each line below names what is still absent and cites the evidence for what is no longer absent.

- **Users and roles.** `GET /users/me` is the only `/users` route — no list, no patch, no deactivate; and no operation anywhere names roles or permissions, so the dashboard cannot show what a role can do or revoke one. (Invitations, by contrast, are whole: accept, list, create, delete, plus the per-tenant variant.)
- **Inventory transfers.** `GET /warehouses` answers; there is no transfer create/list/move operation, so stock can only be corrected by writing movements directly.
- **Conversation detail.** `/conversations/{id}` has messages, assign, close and read, but no read of the conversation itself — the drawer re-derives it from the list row.
- **Webchat visitors still cannot receive.** `POST /webchat/{public_key}/messages` is the only public operation; there is no visitor-side read or stream, which is why the widget is one-way.
- ~~Order: payments create, refunds, cancel, customer/number/date filters, payments+history detail, shipping update~~ — every one of these is an operation today (`/api/v1/orders` GET+POST, `{id}/payments` GET+POST, `{id}/payments/{id}/refunds`, `{id}/cancel`, `{id}/status-history`, `PATCH {id}/shipping`, and the three M8 filters on the list page; see M8 above for the commits and tests that closed the row).
- ~~Inbox views; saved views; global health~~ — `GET /api/v1/inbox` is §137's read model (row above), `/api/v1/platform/saved-views` is full CRUD (5 operations), `GET /api/v1/platform/health` answers. `my-work` is a screen with no endpoint of its own; it composes `/api/v1/inbox?assignee_user_id=`, which is a legitimate design, not a gap.
- ~~Jobs API (GET/retry/cancel); approvals decide endpoint~~ — `/api/v1/jobs` has list/detail/retry/cancel, `POST /api/v1/ai/approvals/{id}/decide` answers. What is still missing here is the **approvals UI**, not the endpoint.
- ~~platform-admin plane~~ — `/api/v1/platform/admin/tenants` list/detail and `PATCH …/{tenant_id}/status` exist. Note: the detail route answered 500 for every tenant until `4dcb7a9` — it was written against a column `outbox_events` does not have.
- Customer record page (360 tabs/timeline) — the API side is there (`/customers/{id}/360`, tags, notes); the page's completeness is tracked in §5 of the frontend audit, not here.

## 6. Spec compliance snapshot

§177 non-negotiable rules: 14 PASS · 11 PARTIAL · 5 FAIL (FAIL: rule 11 module
boundaries, rule 21 provider event ordering, rule 24 entitlement enforcement, rule 28
external SoT policies, rule 29 tenant-scoped restore).
§176 pre-production gate: **the 13 scenarios this register listed as missing each have a dedicated
file now** — `backend/tests/gate/` holds 14 files and 86 cases (`test_gate.py` plus one per named
scenario: out-of-order receipts, stale-run cancellation, tool-scope attack, n8n outage, Redis outage,
DLQ replay, payment UNKNOWN, oversell concurrency, tenant restore, noisy neighbour, realtime resync,
event schema compat, duplicate tool call). Locally 24 of the 86 run and 67 skip for want of a
database, so **which of the 23 scenarios pass is a CI fact, not a file-existence fact** — this line
is a count of what is written, and the run that proves it is recorded in
`docs/ROADMAP_TO_90.md` §8.

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
