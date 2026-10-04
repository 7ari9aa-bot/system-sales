# ADR Index — Two Namespaces, One Rule

The repository contains **two** ADR homes whose numbers collide. This page is the single index for
both (spec §174 "ADR INDEX"). It exists because "ADR-013" on its own currently names two different
documents.

| Home | Files | Number range | What it is | Citation form |
|---|---|---|---|---|
| [`docs/adrs/`](adrs/) | 47 individual files | `ADR-013` … `ADR-059` | The **project's live decision record**. `ADR-013`…`ADR-047` are the decision list the architecture spec enumerates in §174 (the titles in `docs/spec/ARCHITECTURE_PATCH_125-177.txt:2248-2284` match these files one-for-one, e.g. "ADR-014 Conversation Serialization & AI Cancellation", "ADR-025 Channel Account Lifecycle"). `ADR-048`…`ADR-058` are the team's own wave records, added after §174 was written. | bare `ADR-0NN` |
| [`docs/adr/`](adr/) | 5 bundled files | `ADR-001` … `ADR-041`, **sparsely** (25 decisions, not 41) | A separate bundle set, also project-authored, that reads as a baseline/first-pass record: `ADR-001`…`ADR-012` state decisions *against* spec sections (`docs/adr/ADR-001-to-004.md:6` "Spec §47 requires `amount_minor` … Our schema stores `Numeric(14,2)`"), and `ADR-013`…`ADR-041` restate several §174 topics in their own words with narrower content. | `SPEC ADR-0NN` |

**The rule.** A bare `ADR-0NN` means `docs/adrs/` — the project's live record. The bundle in
`docs/adr/` is cited as `SPEC ADR-0NN`. **Neither family is renumbered**: renumbering 47 files plus
every citation in `GAP_REGISTER.md`, `COMPLIANCE_MATRIX.md`, `ROADMAP_TO_90.md`, the `docs/spec/`
reviews and code comments would rot more references than it fixes, and the overlap is removed by
declaration, not by renumbering.

Numbers that exist in only one home (`SPEC ADR-001`…`012` and `ADR-042`…`058`) resolve
unambiguously either way. Within the 13-number collision zone below, a bare citation is ambiguous
unless the reader applies the rule. Legacy bare citations pointing at the bundle do exist and should
be read as `SPEC ADR-0NN` (`docs/ROADMAP_TO_90.md:166` "ADR-001 says keep `Numeric(14,2)`";
`docs/adr/ADR-005-to-012.md:18` cross-references "(ADR-042)" for a future SSE nonce — under this
rule that token now resolves to `docs/adrs/ADR-042-notifications.md`, which is Notification
Infrastructure, not an SSE nonce. Left as-is; noted as a defect to fix in the bundle body
separately).

---

## 1. Project record — `docs/adrs/` (47 files)

Status and `**Spec:**` are transcribed from each file's own header. Where a file declares no status
or no `**Spec:**` line, that is written out rather than inferred.

| # | Title | Date | Status | Spec | What it decided |
|---|---|---|---|---|---|
| ADR-013 | Tenant Context Across Execution Modes | 2026-09-21 | Accepted | §125 | Every execution path (HTTP, webhook, worker, outbox relay, Redis consumer, scheduled job, n8n callback, AI run, maintenance/billing/retention/analytics job) must set a transaction-scoped tenant context before touching tenant-scoped data. |
| ADR-014 | Conversation Serialization & AI Cancellation | 2026-09-21 | Accepted | §126 | One state-mutating processor per conversation, via a DB-backed conversation lease with fencing/version; DB advisory locks and Redis locks rejected as alternatives. |
| ADR-015 | Event Consumer Idempotency | 2026-09-21 | Accepted | §127 | `processed_events` inbox with unique `(consumer_name, event_id)`; the marker and the business effect commit in the same transaction. |
| ADR-016 | Outbound Message Delivery State Machine | 2026-09-21 | Accepted | §129-130 | QUEUED→SENDING→SENT→DELIVERED→READ with FAILED/UNKNOWN branches; UNKNOWN is reconciled by provider status lookup, never blind-retried. |
| ADR-017 | PII Data Lifecycle / Deletion Propagation | 2026-09-21 | Accepted | §131, §172 | A data classification map plus a fixed deletion-propagation order over every store (primary → search → vector chunks → analytics → memory → n8n → derived). |
| ADR-018 | AI Untrusted Input & Tool Scope Security | 2026-09-21 | Accepted | §132 | Strict SYSTEM/POLICY vs UNTRUSTED CONTEXT split; tool arguments bound server-side against the allowed customer/conversation/tenant scope. |
| ADR-019 | Human Approval Workflow | 2026-09-21 | Accepted | §135 | ApprovalRequest/ApprovalStep/ApprovalDecision as first-class entities; a high-risk AI run persists WAITING_APPROVAL and resumes or stops. |
| ADR-020 | n8n vs Internal Workflow Ownership | 2026-09-21 | Accepted | §136 | Our DB holds the canonical workflow definition; n8n is an execution adapter; tenant credentials are Secret References, callbacks use an Automation Actor + tenant-scoped token. |
| ADR-021 | Cross-Module Read Architecture | 2026-09-21 | Accepted | §137 | A dedicated read/query layer over read contracts, read models, approved views and analytics; no cross-module repository calls. |
| ADR-022 | Sagas / Process Managers | 2026-09-21 | Accepted | §139 | Explicit persisted saga state machine where every step has execute() and compensate(); compensation runs in reverse order. |
| ADR-023 | High-Volume Identity & Dedupe Strategy | 2026-09-21 | Accepted | §142 | A dedicated `InboundMessageDedupe` table on `(tenant_id, channel_account_id, external_message_id)`, separating dedupe from partition/retention lifecycle. |
| ADR-024 | Tenant Fairness / Queue Governance | 2026-09-21 | Accepted | §144 | Per-tenant concurrency, queue, rate, AI and campaign budgets, with a fixed priority order topping out at human responses. |
| ADR-025 | Channel Account Lifecycle | 2026-09-21 | Accepted | §145 | Seven-state ChannelAccount lifecycle (PENDING→…→DISABLED) covering token refresh, provider mapping, quality metadata, rate limits, webhook health. |
| ADR-026 | Auth / Platform Admin Separation | 2026-09-21 | Accepted | §146-147, §160 | A separate platform-admin plane with its own permissions and audit scope, an `is_platform_admin` JWT claim, and time-limited, audited break-glass access. |
| ADR-027 | Realtime Recovery | 2026-09-21 | Accepted | §149 | Per-connection id + cursor; on reconnect re-authenticate and re-check tenant/role, resume from cursor or resync, revoke if authority changed. |
| ADR-028 | Canonical Entity & Ownership Model | 2026-09-21 | Accepted | §150-151 | Every entity carries an explicit `ownership_scope` (Tenant/Workspace/Location) and RLS reflects the full hierarchy. |
| ADR-029 | Durable Event Log vs Outbox | 2026-09-21 | Accepted | §152 | Outbox is a temporary reliable-publication buffer, EventLog an append-only durable history; both written in the same transaction. |
| ADR-030 | Durable Scheduler | 2026-09-21 | Accepted | §154 | A PostgreSQL `ScheduledJob` table claimed with `FOR UPDATE SKIP LOCKED`, supporting cancel/reschedule/retry and re-checking preconditions at execution. |
| ADR-031 | Provider Event Ordering | 2026-09-21 | Accepted | §130 | Out-of-order provider events are stored and reconciled on provider_timestamp + provider_event_id + transition rules, not on received_at. |
| ADR-032 | Canonical Message Model | 2026-09-21 | Accepted | §155 | All channels normalize into one canonical message model; unsupported content is marked and its raw metadata preserved. |
| ADR-033 | Conversation Lifecycle | 2026-09-21 | Accepted | §156 | Explicit OPEN/WAITING_CUSTOMER/WAITING_HUMAN/WAITING_AI/PAUSED/CLOSED lifecycle with reopen, new-subject, takeover and merge rules. |
| ADR-034 | Event Schema Evolution | 2026-09-21 | Accepted | §153 | schema_version + aggregate_version on every event; breaking changes require a new version; producer and consumer contract tests. |
| ADR-035 | Knowledge Visibility | 2026-09-21 | Accepted | §157 | A visibility field per document/chunk and a filter pipeline (tenant → permission → visibility → agent policy) before context. |
| ADR-036 | AI Memory Governance | 2026-09-21 | Accepted | §158 | A memory write policy (type, source, verification, confidence, retention) that separates "customer said X" from "system verified X"; staff may review/invalidate. |
| ADR-037 | Public Customer Plane / Payment Boundary | 2026-09-21 | Accepted | §159 | A separate customer-facing plane behind a public gateway, with payments via hosted page or tokenization and never raw card data. |
| ADR-038 | External Commerce Source of Truth | 2026-09-21 | Accepted | §161 | A per-entity SourceOfTruthPolicy (INTERNAL/EXTERNAL/HYBRID) with sync direction, conflict policy and version stamps; CSV import goes through domain services. |
| ADR-039 | Runtime Topology / Redis Failure | 2026-09-21 | Accepted | §162-163 | Stateless API and externalized realtime state; Redis failure is not data loss because Outbox/EventLog/DB are the recovery source. |
| ADR-040 | Tenant-Scoped Recovery | 2026-09-21 | Accepted | §164 | Soft-delete/tombstones plus restore-to-isolated-DB, extract and validate one tenant; never restore the whole production DB over other tenants. |
| ADR-041 | Entitlement Enforcement | 2026-09-21 | Accepted | §165 | A central EntitlementService called by every application service, in a fixed Auth→Tenant→Permission→Entitlement→Domain→Execute order. |
| ADR-042 | Notification Infrastructure | 2026-09-21 | Accepted | §166 | Notification/Preference/Delivery/Digest entities with dedupe_key, quiet hours and digest policy, so 40 updates become one digest. |
| ADR-043 | Metric Definition Registry | 2026-09-21 | Accepted | §167 | A versioned MetricDefinition registry carrying each metric's filters, timezone, business-hours, currency and refund treatment, shared by every dashboard. |
| ADR-044 | SLO / Alerting | 2026-09-21 | Accepted | §168 | An SLO catalog (availability, outbox lag, queue depth, DLQ, AI fallback, provider errors…) each with warning/critical thresholds, owner, destination and runbook. |
| ADR-045 | AI Evaluation & Rollout | 2026-09-21 | Accepted | §169 | Eval dataset → offline evaluation → safety checks → regression comparison → approve → canary ramp (5/25/50/100) → monitor → automated rollback. |
| ADR-046 | Channel Test Environments | 2026-09-21 | Accepted | §170 | Environment-scoped channel configuration; dev and staging use test credentials and are never wired to production channels by default. |
| ADR-047 | Billing Metering Integration | 2026-09-21 | Accepted | §171 | Provider usage event → usage meter → billing, with idempotency keys; billing consumes canonical events, not UI-calculated values. |
| ADR-048 | Entity Ownership Scope Concretization | 2026-09-23 | Accepted (amends ADR-028) | §151 (Q4) | A concrete per-entity ownership map (Location/Workspace/Tenant) enforced by the write path, replacing ADR-028's "per business decision" open question. |
| ADR-049 | AI Egress Classification and Data Residency | 2026-09-23 | Accepted | §43 | Payloads self-classify: `policy.classify_data()` returns `restricted` for text carrying a direct identifier, using the same patterns the redactor masks. |
| ADR-050 | Inbound Voice Transcription Orchestration | 2026-09-23 | Accepted | §35–36 | `transcribe_inbound_voice()` belongs in the worker layer — the only place that legitimately sees both the attachment table and the AI budget gate. |
| ADR-051 | Shipments and the order saga move through the paths that already guard them | 2026-09-23 | **not declared** | **none declared** (prose cites §139, §140, §17) | Shipping is one operation: `create_shipment` requires `processing` and moves the order through the guarded `_transition` path, and `orders.process_state` gains a real saga caller. |
| ADR-052 | The goods-return process runs on the saga engine | 2026-09-23 | **not declared** | **none declared** (prose cites §139, §140, §115, §22) | Returns run as a persisted process on `core/saga.py`, with `orders.process_state` staying the lifecycle authority; file states it supersedes ADR-051 decision 2. |
| ADR-053 | A tenant trades in one currency, so a second currency is a refusal | 2026-09-23 | **not declared** | **none declared** (prose cites §47, §48) | `tenants.currency` is the single answer to "what currency is money here", read from the request context or `resolve_tenant_currency()`; a mismatched currency is refused. |
| ADR-054 | A refund is a ledger row, so refund state is derived and never stored | 2026-09-24 | **not declared** | **none declared** (prose cites §57, §66, §2, §139) | Refunds are rows in `refunds` written in exactly one place under `FOR UPDATE`; refund state is derived from the ledger, and `reconcile_payment` may no longer downgrade a captured payment. |
| ADR-055 | Correcting where an order is going is a versioned write that publishes | 2026-09-24 | **not declared** | **none declared** (prose cites §19, §153, §1) | `update_shipping` is a compare-and-set write with the expected version in its WHERE clause, publishing an outbox event carrying a real `aggregate_version`. |
| ADR-056 | A contact handle is canonicalized on write, and a damaged one is marked, not rewritten | 2026-09-24 | **not declared** | **none declared** (prose cites §146, §53) | One stdlib-only normalizer (`core/contact_norm.py`) owns handle canonicalization; unparseable handles are marked and quarantined for an operator rather than rewritten. |
| ADR-057 | An approval is decided once, honoured once, and a partial queue says so | 2026-09-24 | **not declared** | **none declared** (prose cites §135) | The approval row is the lock on both sides — `SELECT … FOR UPDATE` in `decide` and `find_granted` — so a grant can be consumed exactly once, and a capped pending queue reports itself as partial. |
| ADR-058 | The consumer inbox is claimed before the effect, not checked beside it | 2026-09-24 | **not declared** | **none declared** (prose cites §127) | The claim is a transaction-scoped `pg_try_advisory_xact_lock` keyed on `(consumer_name, event_id)`; the marker is checked inside the lock and inserted in the same transaction as the effect. |

| ADR-059 | The desktop's network calls leave from Rust, so the API needs no CORS change | 2026-09-25 | **Accepted** (Session A confirmed decision 3 the same day) | desktop mission §2, §3.2, §3.6, §5 | Every desktop request — including the SSE stream, which carries `Authorization: Bearer` — is issued by the Rust process behind the `http` port, so the webview never makes a cross-origin call and `CORS_ORIGINS` gains no Tauri origin. The boundary lint is what enforces it (`config/check-platform-boundary.mjs` fails the build if the React tree calls `fetch`). The ADR's separate request that the server narrow `?token=` (R5) is open. |

| ADR-060 | V12 adopted in place: the authority chain covers human actors too, payments stay provider-agnostic, the three-phase program replaces the §42 restructure | 2026-09-26 | Accepted | SALES OS V12 (62 invariants) vs `docs/SYSTEM_BASELINE.md` | The V12 authority-centered program is adopted without a restructure: Decision → Capability → Authority Lease → Atomic Execution covers human and AI actors alike, payments remain behind a provider-agnostic port, and the remaining invariants land as the three-phase V12 program. |

| ADR-061 | The Commerce Core is a bounded domain the platform depends on, not the reverse | 2026-10-04 | Accepted | §178–§190 | Catalog/Inventory/Commerce are formalized as one bounded Core with the binding dependency rule (Agent → Capabilities → Application APIs; Analytics ← events only); the existing inventory ledger, order/payment machines and idempotency layers are adopted as the v1.0 semantics; catalog identifiers land before any POS work; discrepancies are findings, never silent fixes. Narrative: `docs/COMMERCE_CORE_ARCHITECTURE.md`. |

Coverage: 49 files in `docs/adrs/`, 49 rows above. Verified with
`ls docs/adrs | wc -l` == `awk '/^## 1\./,/^## 2\./' docs/ADRS.md | grep -c "^| ADR-"`.
(The row prefix `^| ADR-` also opens the §3 collision and §4 caveat tables, so an
unscoped `grep -c` over the whole file counts more and verifies nothing — that is how
this line read 46 == 46 while §1 held 46 rows and the count had already moved on.)

---

## 2. Bundle set — `docs/adr/` (25 decisions in 5 files)

**These are not 41 decisions.** The bundle *filenames* advertise ranges (001–004, 005–012, 013–022,
023–025, 026–041), but only 25 numbered decisions are actually present. `ADR-001`…`ADR-012` use an
`# ADR-0NN:` H1 with no `### Status` subsection, so their status is undeclared; `ADR-013`…`ADR-041`
use `## ADR-0NN:` with an `### Status` of Accepted.

| # | Title | Status | Bundle file |
|---|---|---|---|
| SPEC ADR-001 | Money representation — Numeric(14,2) not amount_minor | not declared | `docs/adr/ADR-001-to-004.md` |
| SPEC ADR-002 | Secrets — Supabase Vault behind SecretStorePort | not declared | `docs/adr/ADR-001-to-004.md` |
| SPEC ADR-003 | API versioning — /api/v1 mount now | not declared | `docs/adr/ADR-001-to-004.md` |
| SPEC ADR-004 | Pagination — cursor-based | not declared | `docs/adr/ADR-001-to-004.md` |
| SPEC ADR-005 | SSE Authentication — ?token= Query Param Fallback | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-006 | Multi-Tenancy — PostgreSQL RLS + Session GUCs | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-007 | Domain Events — Redis Streams Outbox Pattern | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-008 | Payments — Stripe + Unknown State Reconciliation | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-009 | AI Budget Enforcement — Hard Cap Before Each Call | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-010 | Global Search — SearchPort Abstraction | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-011 | Notifications — Unified Model in platform.models | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-012 | Privacy — Data Erasure via Consent Ledger | not declared | `docs/adr/ADR-005-to-012.md` |
| SPEC ADR-013 | Tenant Context Across Execution Modes | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-014 | Conversation Serialization | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-015 | Event Consumer Idempotency | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-016 | Outbound Message Delivery State Machine | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-019 | Human Approval Workflow | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-022 | Sagas / Process Managers | Accepted | `docs/adr/ADR-013-to-022.md` |
| SPEC ADR-023 | Customer 360° Identity Merge & Deduplication | Accepted | `docs/adr/ADR-023-to-025.md` |
| SPEC ADR-024 | Inventory Reservations & TTL-Based Auto-Release | Accepted | `docs/adr/ADR-023-to-025.md` |
| SPEC ADR-025 | Inbound Channel Webhook Deduplication & Cryptographic Verification | Accepted | `docs/adr/ADR-023-to-025.md` |
| SPEC ADR-026 | Auth / Platform Admin Separation | Accepted | `docs/adr/ADR-026-to-041.md` |
| SPEC ADR-029 | Durable Event Log vs Outbox | Accepted | `docs/adr/ADR-026-to-041.md` |
| SPEC ADR-039 | Runtime Topology / Redis Failure | Accepted | `docs/adr/ADR-026-to-041.md` |
| SPEC ADR-041 | Entitlement Enforcement | Accepted | `docs/adr/ADR-026-to-041.md` |

Absent from this home (numbers advertised by the bundle filenames but with no section):
`017, 018, 020, 021, 027, 028, 030–038, 040`. Notably **`SPEC ADR-017` does not exist** — PII
lifecycle is `ADR-017` in `docs/adrs/` and is also §174's own entry, so it is not a collision.

---

## 3. COLLISION LIST — 13 numbers present in BOTH homes

Each row was compared by reading both bodies. "Relationship" states only what the two bodies
actually say; where they do not speak to each other, it says so.

| # | `docs/adr/` (SPEC ADR-0NN) | `docs/adrs/` (ADR-0NN) | Relationship |
|---|---|---|---|
| 013 | Tenant Context Across Execution Modes | Tenant Context Across Execution Modes | Same title, compatible intent, **different scope list**: the bundle covers 4 modes (HTTP, workers, scheduled jobs, SSE); the project file covers the 12 execution paths the spec enumerates in §125. The project record is the broader one; no contradiction. |
| 014 | Conversation Serialization | Conversation Serialization & AI Cancellation | **Contradiction on mechanism.** The bundle decides on `pg_try_advisory_xact_lock`; the project file lists "Database-level advisory locks" as a *rejected* alternative and decides on a DB-backed lease with fencing token. The project record supersedes here (and `ADR-058` now uses an advisory lock for a different concern, so the rejection is scoped to conversation serialization). |
| 015 | Event Consumer Idempotency | Event Consumer Idempotency | Same goal, **three different mechanisms across the repo**: bundle = `INSERT … ON CONFLICT DO NOTHING` and skip if zero rows, keyed `(tenant_id, consumer_group, event_id)`; project = marker and effect in one transaction, keyed `(consumer_name, event_id)`; `ADR-058` (Accepted, later) reports that the code actually did check-beside-effect and moves the claim to a transaction-scoped advisory lock. `ADR-058` supersedes both 015 bodies as the description of the running system. |
| 016 | Outbound Message Delivery State Machine | Outbound Message Delivery State Machine | Agreement on the state machine and on "never blind-retry UNKNOWN". The project record adds idempotency keys and out-of-order handling (§130 → `ADR-031`); no contradiction. |
| 019 | Human Approval Workflow | Human Approval Workflow | Bundle describes a two-phase pattern (pending row + notification + dispatch); the project record concretizes it into ApprovalRequest/Step/Decision with a persisted WAITING_APPROVAL run state, expiry and staleness on new customer messages. Consistent; project version is the implementation-shaped one. (`ADR-057` later hardens its once-only grant.) |
| 022 | Sagas / Process Managers | Sagas / Process Managers | Bundle decides DB-backed orchestration via reservation states with no compensation concept; project record adds the explicit execute()/compensate() engine persisted in `sagas`. Concretizes and extends; no contradiction. `ADR-051`/`ADR-052` are the first real callers of that engine. |
| 023 | Customer 360° Identity Merge & Deduplication | High-Volume Identity & Dedupe Strategy | **Different subject matter sharing a number.** Bundle = customer identity merge protocol (`customer_identities`, `merged_into_id`, reparenting, `identity_merge_events`). Project = an `InboundMessageDedupe` table for provider message ids. Neither body mentions the other; **relationship not established**, and neither should be read as implementing the other. |
| 024 | Inventory Reservations & TTL-Based Auto-Release | Tenant Fairness / Queue Governance | **Different subject matter sharing a number.** Bundle = two-phase inventory reservations with a 15-minute lease and expiry worker. Project = per-tenant queue budgets and work priority. **Relationship not established.** The bundle's reservation decision has no same-number counterpart in `docs/adrs/`. |
| 025 | Inbound Channel Webhook Deduplication & Cryptographic Verification | Channel Account Lifecycle | **Different subject matter sharing a number.** Bundle = provider signature verification plus a two-tier dedupe whose Tier 1 is a Redis `SET NX` key; project = the seven-state ChannelAccount lifecycle. **Relationship not established** — and note the bundle's Redis-dedupe tier conflicts with the rejection of Redis dedupe recorded in `ADR-015` and `ADR-023`. |
| 026 | Auth / Platform Admin Separation | Auth / Platform Admin Separation | Same decision, stated through different mechanisms: bundle puts the flag on the `users` table and sets it out-of-band; project carries an `is_platform_admin` JWT claim and adds scoped, time-limited, audited break-glass access. Compatible if the claim derives from the column — **that derivation is not stated in either body**, so it is not established. |
| 029 | Durable Event Log vs Outbox | Durable Event Log vs Outbox | Agreement: both write in the same transaction, both separate the transient publication buffer from the durable log. Project record adds the operational consequences (replay from EventLog, aggressive Outbox trimming). No contradiction. |
| 039 | Runtime Topology / Redis Failure | Runtime Topology / Redis Failure | Same title and same PostgreSQL-as-source-of-truth stance. The bundle additionally mandates that the **rate limiter fails OPEN** when Redis is unreachable; the project record does not mention rate limiting at all. **Relationship on the fail-open rule not established** — do not read `ADR-039` as confirming or denying it. |
| 041 | Entitlement Enforcement | Entitlement Enforcement | Agreement on centralized, service-layer enforcement with structured 402/403. Bundle names `check_feature_enabled(...)` call sites; project record decides a single EntitlementService with a fixed check order. Consistent; project version is the concrete one. |

**Not collisions** (present in `docs/adrs/` only, despite falling inside the bundles' advertised
ranges): `017, 018, 020, 021, 027, 028, 030–038, 040`.

---

## 4. Status caveats

Each row below was a case where a file said `Accepted` while the claim could not be confirmed from
the repo's own evidence. They have since been re-measured against `backend/app`; the verdict column
records what the code actually does today, and `docs/COMPLIANCE_MATRIX.md` carries the same finding
in the row it belongs to.

| ADR | Status | Finding, then verdict (2026-09-24) |
|---|---|---|
| ADR-024 | Accepted | Was: matrix marked §144 ⬜. **Resolved — §144 is implemented and charged on the consumption path** (`core/fairness.py:68,112,142`; `workers/base.py:252`; `campaign_worker.py:41`; `ai/gateway.py:544`). The ADR was right; the matrix row was the stale claim. |
| ADR-026 | Accepted | Was: matrix marked §146 ⬜, §147 ⬜, §160 ⬜. **Resolved on all three** — MFA/TOTP is wired into the login path (`identity/service.py:339-341`), break-glass is a service and a route (`core/break_glass.py`, `platform/router.py:995`), and the §160 plane exists and is gated on the global claim (`platform/router.py:625,656,698,995`). §146's **SSO half stays open**: only a Redis subject-link at `core/mfa.py:441`, no IdP handshake. |
| ADR-040 | Accepted | `**Spec:** §164` — matrix still marks §164 ⬜ (tenant-scoped restore is an ops procedure, and nothing in `backend/app` performs it). **Open; the ADR describes a design, not a built path.** |
| ADR-042 | Accepted | Was: matrix marked §166 ⬜. **Resolved — §166 has both halves** (`NotificationService.digest` at `service.py:222`, route `GET /notifications/digest`), with one honest remainder: `notifications/digest.py`'s `NotificationDigest` table has no production importer. |
| ADR-044 | Accepted | `**Spec:** §168` — matrix still marks §168 ⬜ (grep "SLO" in `backend/app` → no matches). **Open.** |
| ADR-021 | Accepted | Was: matrix marked §137 ⬜ "no such module exists". **Resolved — `InboxQuery` exists and is the route the inbox calls** (`conversations/router.py:149`). |
| ADR-045 | Accepted | Was: matrix marked §169 ⬜, "0 callers". **Half-resolved** — `AIEvaluationService` is called from `ai/router.py:552,566,578`, so it is no longer dead; the row stays 🟡 because nothing records an evaluation from a real run, and no test names `/evaluations`. |
| ADR-015 / ADR-058 | Accepted / both declared | Was: ADR-058 declared nothing while contradicting ADR-015's account. **Resolved — `ADR-058` now states `**Status:** Accepted — corrects ADR-015's "marker and effect in the same transaction" account`**, so a reader cannot mistake the older description for current behaviour. |
| ADR-051 … ADR-058 | all declared | **Resolved** — all eight files now carry `**Status:**`, `**Date:**`, `**Spec:**` and `**Related:**`, with the supersession chain stated where it exists (ADR-052 supersedes ADR-051 decision 2; ADR-058 corrects ADR-015). Spec anchors were taken from `docs/spec/` + the matrix rows, not from the prose. |
| ADR-013 | Accepted | Was: matrix recorded §125 as ❓ "no requirement text recoverable". **Resolved — the row was the stale claim on both counts**: the requirement text is at `docs/spec/ARCHITECTURE_PATCH_125-177.txt:11`, and the rule is implemented on every named execution mode. |
| §117 row | — | **Resolved** — the matrix row no longer says `docs/adr/` holds "5 files, ADR-001…041"; it now counts decisions (25 bundled, numbered within `ADR-001`…`ADR-041`, 13 colliding) and names both homes. |
| `docs/adr/ADR-005-to-012.md:18` | — | Unchanged: cross-references "(ADR-042)" for an SSE nonce, which under §1's rule resolves to `docs/adrs/ADR-042-notifications.md` — a different decision. A bundled upstream file; the body is left as written and the collision is documented here instead. |

---

## 5. How to cite

- New text: `ADR-0NN` for `docs/adrs/`, `SPEC ADR-0NN` for `docs/adr/`, always with the row above in
  mind for the 13 collision numbers.
- When citing a collision number, name the file the first time: `ADR-014`
  (`docs/adrs/ADR-014-conversation-serialization.md`).
- Do not describe the two same-numbered documents as agreeing unless §3 says so.

## D16 — Sales Intelligence rides Novita/GLM

| Decision | File |
|---|---|
| D16: the SI agent's strong/fast models ride Novita's OpenAI-compatible API (`zai-org/glm-5.3`, `zai-org/glm-5.3-flash`), configured per tenant via `model_configs` — recorded before the first real SI run. | [`docs/adrs/D16-si-provider-novita-glm.md`](adrs/D16-si-provider-novita-glm.md) |
