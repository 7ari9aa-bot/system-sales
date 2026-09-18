# Master Build Plan — Zero-Deferral Edition (binding)

Directive (2026-09-18): NOTHING technical is deferred. Only external platform
connections (WhatsApp/Meta, etc.) wait for credentials. Supersedes any
"deferred" notes in earlier docs and ADRs.

## Execution model

- Build wave N → dispatch 2 REVIEW agents (gap-hunting vs spec §1-177) →
  fix findings while starting wave N+1 → merge review fixes.
- Review agents get: the spec sections, the diff scope, and one job — find
  gaps/violations, no new features.

## Waves (all adopted, zero deferrals)

- **W1 (running)** — /api/v1 + error contract v2 + cursor pagination +
  VersionMixin + event envelope v2 + WebhookEvent + retry classification.
- **W1.5 (me, after W1 merge)** — ProcessedEvent inbox + EventLog + outbox
  lease columns + migration; conversation lease/serialization + ownership
  states; outbound state machine (QUEUED/SENDING/SENT/UNKNOWN/DELIVERED/READ/
  FAILED) + reconciliation worker; durable Reservation entity (expires_at,
  status); UUIDv7 helper adopted for all NEW tables.
- **W2** — Tenancy hierarchy FULL retrofit: workspaces + locations tables,
  workspace_id/location_id added to every tenant-scoped table
  (expand-contract migration), RLS upgraded to hierarchy; identity
  resolution/merge (merge candidates/events, merged_into); message templates
  (+approvals) as first-class; consent entity; attachments + media pipeline
  (quarantine/scan statuses); ChannelAccount lifecycle states; canonical
  message content model; tombstones/soft-delete on sensitive entities;
  inventory Reservation service integration into orders.
- **W3 — AI governance (full)** — untrusted-input boundary, tool scope
  binding (conversation/customer server-side), run limits (max_steps/tools/
  wall_time/handoffs), durable Approval workflow (request/step/decision,
  WAITING_APPROVAL resume), per-tenant budget reserve/settle + thresholds +
  alerts, provider data-governance policy, knowledge visibility levels +
  permission-filtered retrieval, memory write governance, AI trace
  (correlation/causation in every run), evaluation pipeline tables +
  canary/rollback statuses.
- **W4 — Business systems** — Segment (single shared entity, DSL AST),
  Task system, Job system (Job entity + progress + retry/cancel), durable
  ScheduledJob scheduler + poller, SearchPort (PG FTS + trigram), SLA
  policies + BusinessCalendar/Hours/Holiday, tenant lifecycle
  (provisioning→deleted) + offboarding async job, EntitlementService
  centralization (CanX checks in one service), layered rate limits
  (tenant/user/endpoint), sagas for order→payment→fulfillment state machine,
  metric definitions registry.
- **W5 — Frontend rebuild** — Tailwind v4 + shadcn/ui + TanStack Table +
  TanStack Query, design tokens, new application shell (grouped sidebar IA
  per spec §89), command palette (Ctrl+K), Home (needs-attention → KPIs →
  pulse), My Work, Inbox with views + context tabs, Customer 360 record +
  quick preview drawer, saved views, notifications center, global health
  indicator, undo/confirm patterns, skeleton loading, realtime recovery
  (connection_id + cursor + resync), optimistic UI (safe actions only),
  responsive + a11y + RTL-native (logical properties).
- **W6 — Platform & hardening** — SecretStorePort + Supabase Vault +
  credentials migration; privacy domain (consent enforcement, data subject
  requests, deletion propagation chain incl. search/vector/memory/n8n);
  retention workers; billing metering pipeline + immutable period snapshots +
  invoice lines; platform admin plane + break-glass access; security events
  table + audit enrichment; feature flags; notification dedupe/digest/quiet
  hours; partition-ready tables (messages/audit/ai_usage/webhook_events) +
  archiving jobs; SLO catalog + alert hooks; staging environment + backup
  restore drill; tenant-scoped restore procedure; §176 pre-production gate
  (23 scenarios as tests/gate/).

## Review protocol (after EVERY wave)

2 review agents dispatched in background with:
1. The spec sections the wave covers (verbatim).
2. The list of files the wave touched.
3. Instruction: find gaps/violations/inconsistencies ONLY — no new features,
   no refactors. Output: numbered findings with file:line and severity
   (blocker/major/minor).
Main agent triages: blockers fixed immediately in the next wave, minors
batched at wave end. Findings log: docs/reviews/wave-N.md.
