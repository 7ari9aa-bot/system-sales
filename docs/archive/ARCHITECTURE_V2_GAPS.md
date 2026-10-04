# Architecture V2 Gap Analysis — 124-Point Spec vs Built System

Spec date: 2026-09-18. Status legend: ✅ compliant · 🟡 partial · ❌ missing ·
📝 diverged (ADR needed). Work is organized in waves (§123 order preserved).

> **This table is the 2026-09-18 gap snapshot, not live status.** Rows updated to
> 2026-09-23 below are the ones re-verified against the code during Wave 3; every
> other row still shows its snapshot value. `docs/COMPLIANCE_MATRIX.md` is the
> live, per-point status record and is the authority for current state.

## Compliance snapshot

| Spec § | Topic | Status | Notes / Wave |
|---|---|---|---|
| 1–5 | Vision, layers, modular monolith | ✅ | Built as specified |
| 6 | Application layer use cases | 🟡 | Services exist; naming as explicit use-case classes → W1 |
| 7–8 | Domain + module boundary rule | 🟡 | Boundaries honored by convention; no lint/contract enforcement → W1 (import-linter) |
| 9 | Ports & Adapters | 🟡 | EventBus exists; PaymentProvider/AIProvider/Storage/SecretStore ports to formalize → W1/W6 |
| 10–11 | Tenancy + RLS (non-bypass runtime) | ✅ | sales_app role + GUC binding + smoke test |
| 12 | Authorization (RBAC + resource-level) | 🟡 | RBAC done; resource-level policies → W4 |
| 13–16 | Actor model, AI tool authz, risk levels, idempotency keys | 🟡 | Tool policies exist; risk_level + idempotency_key per side-effect tool → W3 |
| 17 | Optimistic locking (version) | ❌ | W1: VersionMixin + 409 conflict path |
| 18 | Outbox | ✅ | Same-transaction insert + relay |
| 19 | Event contract (correlation/causation/schema_version) | 🟡 | W1: envelope v2 |
| 20–21 | Streams, consumer groups, retention/replay | 🟡 | Groups + DLQ done; XAUTOCLAIM + replay-from-outbox → W1 |
| 22–24 | Webhook ingress store + retry/DLQ | 🟡 | idempotency_keys only; WebhookEvent table + raw payloads → W1 |
| 25 | Layered rate limiting | 🟡 | IP middleware; tenant/user/endpoint tiers → W4 |
| 26 | Channel gateway | ✅ | Built (whatsapp/telegram/webchat) |
| 27–29 | Identity resolution + merge + Customer 360 | ❌ | W2: merge candidates/events, merged_into, 360 API |
| 30–31 | WhatsApp policy state + Template entity | 🟡 | 24h check in worker; move to domain policy + template tables → W2 |
| 32 | Marketing consent | ❌ | W2: consent entity (purpose/channel-scoped) |
| 33–35 | Media pipeline + Attachment + STT | ✅ | 2026-09-23: full inbound path closed — `conversations/media.py` queues durable audio as `pending`; `workers/message_worker.py` `transcribe_inbound_voice` (budget reserved BEFORE the provider call, §42 settle + spend booked) runs under the conversation lease before the reply; transcript persisted `attachments.transcript_text` (`a7d0f4b2c6e9`); agent context renders voice turns via `ConversationService.audio_transcripts`; 11 DB tests green on CI |
| 36 | Voice | 🟡 | 2026-09-23: STT side done (see 33-35; failures are best-effort, never raise into the worker). Remaining, documented in GAP_REGISTER: TTS has no caller (no auto voice reply yet) and outbound delivery never passes `media_type` |
| 37–38 | AI architecture + memory scoping | ✅ | 2026-09-23: `ai/runtime.py` context builder (instructions → §132 untrusted knowledge turn → memories as their own untrusted user turn → history → message); recall/write scoped tenant+customer with §158 status + expiry filters; ADR-036 provenance annotation |
| 39–40 | RAG + freshness | ✅ | 2026-09-23: `ai/knowledge.py` + HNSW index (`b8c9d0e1f2a3`) |
| 41 | AI output guardrails | ✅ | 2026-09-23: `core/guardrails.py` + `ai/guardrails.py` chain enforced inside `ai/runtime.py` before the answer is returned (allow/block/handover verdict recorded on the run) |
| 42 | AI budget governance (reserve/settle, thresholds) | ✅ | 2026-09-23: `ai/gateway.py` `reserve_budget`/`settle_reservation` + per-tenant `AIBudget` thresholds with alert + fallback/block on exceed |
| 43 | AI provider data governance | ✅ | 2026-09-23: `ai/policy.py` `classify_data` + `decide()` ladder (deny → model allow-list → data residency, fail-closed on unknown region → clearance) applied on both `gateway.chat` and `gateway.embed`, redaction re-applied before send; ADR-049; `tests/test_ai_provider_egress.py` |
| 44 | AI trace (correlation, cost, policy decisions) | ✅ | 2026-09-23: `ai/trace.py` + read routes in `ai/router.py` |
| 45 | SearchPort + FTS | ❌ | W4: PostgreSQL FTS behind SearchPort |
| 46 | Business hours + SLA | ❌ | W4 |
| 47 | Money amount_minor | 📝 | ADR-001: keep Numeric(14,2) Decimal (exact); amount_minor adapter at payment edges |
| 48–50 | Tenant lifecycle + on/offboarding | ❌ | W4 |
| 51–52 | Privacy domain + retention | ❌ | W6 |
| 53–54 | Billing metering + snapshots | 🟡 | usage_records exist; metering pipeline + immutable snapshots → W6 |
| 55–57 | Analytics read models, partition-ready, archiving | ❌ | W6 (messages/audit/ai_usage partition-ready indexes) |
| 58 | Pooling | ✅ | Supavisor + statement_cache_size=0 |
| 59 | Stateless API | ✅ | |
| 60–61 | Realtime + scoped subscriptions | 🟡 | SSE exists; scope keys + realtime gateway → W5 |
| 62 | Automation isolation | ✅ | Internal workflow engine + worker runtime |
| 63–64 | Worker types + retry classification | 🟡 | Pools exist; transient/permanent retry classes → W1 |
| 65–67 | Observability + audit + security events | 🟡 | structlog done; security_events table → W6 |
| 68–69 | SecretStorePort + rotation | ❌ | ADR-002: Supabase Vault behind SecretStorePort → W6 (critical before production WhatsApp tokens) |
| 70–72 | DR + environments + sandbox | 🟡 | Runbook written; staging env + backup drill → W6 |
| 73–75 | CI/CD + expand/contract migrations | ✅ | CI + versioned migrations |
| 76 | Feature flags | ❌ | W6 |
| 77 | Read path discipline | 🟡 | |
| 78 | /api/v1 versioned routes | ❌ | **W1 — breaking: mount all routers under /api/v1** |
| 79 | Cursor pagination | ❌ | W1: cursor helpers, migrate list endpoints |
| 80 | Unified error contract | 🟡 | DomainError exists; add retryable + request_id + codes enum → W1 |
| 81 | Core entity model | 🟡 | ~70% of entities exist; new: merge/segments/tasks/jobs/templates/consent/attachments/workflows → W2/W4 |
| 82 | Segment entity (single, shared) | ❌ | W4 |
| 83–84 | Task + Job systems | ❌ | W4 |
| 85–86 | Frontend arch (Tailwind/shadcn/TanStack, state layers) | ❌ | W5 — full frontend overhaul |
| 87–89 | App shell + sidebar IA | ❌ | W5 |
| 90–96 | Design tokens, tables, saved views, command palette | ❌ | W5 |
| 97–104 | My Work, Home, Inbox views, Customer 360, notifications, health, undo | ❌ | W5 |
| 105–113 | UX rules (skeletons, a11y, optimistic, realtime UX) | 🟡 | Adopt in W5 build |
| 114–116 | Testing architecture incl. security + perf | 🟡 | Backend 126 tests; add security suite + perf suite → W6 |
| 117 | ADRs | ❌ | Started now (docs/adr/) |
| 118–119 | Definitions of Done | 📝 | Adopted as review checklists from now |
| 120–122 | Flows, principles, system map | ✅ | Honored by design |
| 123 | Implementation order | ✅ | Waves follow it |

## Waves (dispatched to the team roster in docs/TEAM.md)

- **W1 — Architecture Guarantees**: /api/v1 mount + error contract v2 + cursor
  pagination + VersionMixin + event envelope v2 (correlation/causation/
  schema_version) + WebhookEvent store + retry classification + import-linter
  module boundaries + ADRs.
- **W2 — CRM/Messaging depth**: identity merge model, message templates,
  consent, attachments/media pipeline, WhatsApp policy in domain.
- **W3 — AI governance**: risk levels + tool idempotency, output guardrails,
  per-tenant budgets (reserve/settle + thresholds), provider governance,
  knowledge versioning, explicit context builder.
- **W4 — Business systems**: Segments (DSL), Tasks, Jobs, SearchPort (PG FTS),
  SLA/business calendars, tenant lifecycle, layered rate limits.
- **W5 — Frontend rebuild**: Tailwind + shadcn/ui + TanStack Table, design
  tokens, new shell/sidebar IA, command palette, Home/My Work/Inbox views,
  Customer 360, saved views, realtime scoping.
- **W6 — Platform hardening**: SecretStorePort (Vault), privacy/retention
  workers, billing snapshots, partition-ready tables, security events, feature
  flags, staging env, security/perf test suites.
