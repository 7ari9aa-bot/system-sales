# Build Plan — Full System, No Feature Cuts

The stages below are **dependency order, not scope reduction**. Every item of the
approved blueprint (§1–§22) maps to exactly one stage. Nothing is de-scoped.

Legend: ☐ pending · ◐ in progress · ☑ done

---

## Stage 0 — Foundation ☑
- [x] Monorepo layout (backend / frontend / infra / docs / CI)
- [x] FastAPI skeleton: app factory, healthz/readyz, config (pydantic-settings)
- [x] Core primitives: db (async engine + session + tenant GUC), redis, tenancy context, security (JWT + bcrypt)
- [x] Event bus interface + Redis Streams implementation (consumer groups, ack, DLQ)
- [x] Worker runtime (retries, exponential backoff + jitter, DLQ routing)
- [x] Outbox relay skeleton (real polling wired in Stage 3)
- [x] docker-compose (postgres 17 + redis 7), CI (ruff + pytest), env template
- [x] Dependencies installed + verified: backend (venv, ruff clean, tests green), frontend (npm build green)
- [ ] GitHub private repo + first push (needs repo name decision)

## Stage 1 — Data Core (full schema) ☑
- [x] Alembic wired to async engine (env.py: DATABASE_URL_ADMIN, begin_transaction, async run_sync)
- [x] IDENTITY: tenants, users, tenant_users, roles, permissions, role_permissions
- [x] CUSTOMERS: customers, customer_identities, addresses, tags, notes, customer_events
- [x] CONVERSATIONS: conversations, messages, assignments, ai_sessions
- [x] PRODUCTS: products, product_variants, categories, brands, product_images, product_prices
- [x] INVENTORY: warehouses, inventory_balances, inventory_movements, inventory_transfers
- [x] ORDERS: orders, order_items, order_status_history, shipments, order_payments, refunds
- [x] MARKETING: campaigns, ad_sets, ads, touchpoints, leads, conversions, attributions
- [x] AI: agents, agent_tools, prompts, model_configs, memories, knowledge_items, agent_runs, tool_calls, model_calls, ai_usage
- [x] PLATFORM: integrations, webhooks, webhook_deliveries, notifications, automations, outbox_events, idempotency_keys, audit_logs
- [x] BILLING: plans, subscriptions, entitlements, usage_records, invoices
- [x] 63 tables total — applied to Supabase (project iixxqitfopsgvaheedlg, eu-west-1) via migration 0b79f7470c1a
- [x] RLS ENABLED+FORCED on every tenant-scoped table, policy keyed on `app.tenant_id` GUC (NULLIF('')-safe); tenant_users also accepts `app.user_id` for login-time membership discovery; audit_logs allows NULL-tenant platform writes
- [x] tenant_id leading in PKs / unique constraints / indexes (sharding-ready)
- [x] pgvector 0.8.2 enabled; Vector(1536) on memories + knowledge_items
- [x] Seeds: 3 roles, 20 permissions, 47 role_permissions, 3 plans
- [x] `sales_app` runtime role (no bypassrls) + grants + default privileges; postgres role kept for migrations only (Supabase postgres has BYPASSRLS — verified)
- [x] RLS isolation smoke test (scripts/rls_smoke_test.py): 7/7 PASS as sales_app
- [x] Engine hardened for transaction pooler: statement_cache_size=0; bind_tenant uses set_config (SET rejects bind params)

## Stage 2 — Identity & Access
- [ ] Auth: register / login / refresh / logout (JWT + rotation)
- [ ] Users CRUD, invitations, tenant switching
- [ ] RBAC enforcement dependencies (permission codes)
- [ ] Tenant resolution middleware → tenancy context → RLS GUC
- [ ] Audit log write path
- [ ] Redis rate limiting middleware

## Stage 3 — Platform Primitives (hardening)
- [ ] Outbox relay service (poll FOR UPDATE SKIP LOCKED, publish, mark)
- [ ] Worker runtime hardening: attempts tracking, DLQ stream + inspector API
- [ ] Circuit breaker utility (AI providers, channels)
- [ ] Idempotency middleware for external webhooks
- [ ] Versioned event schemas (pydantic) + event registry
- [ ] Service authentication for trusted operational consumers

## Stage 4 — Commerce Domain
- [ ] Customers service + APIs (identities, tags, notes, events)
- [ ] Catalog: products / variants / categories / brands / images / prices
- [ ] Inventory: balances, movements, transfers, reserve/release semantics
- [ ] Orders lifecycle + status_history, transactional CreateOrder service
- [ ] Payments + refunds behind a provider-agnostic interface (manual/cash first)
- [ ] Outbox events emitted for every aggregate change
- [ ] Domain unit tests (rules, concurrency, rollback)

## Stage 5 — Messaging
- [ ] Channel Gateway framework: verify → normalize → idempotency → durable ingest
- [ ] WhatsApp Cloud API adapter: webhooks, media fetch→S3 immediately (URLs expire), templates, 24h window handling, rate limits, outbound queue + retries
- [ ] Webchat channel (no external dependencies)
- [ ] Conversations / messages core + assignments
- [ ] Message workers + outbound delivery workers
- [ ] Telegram / Instagram / Messenger adapters on the same interface (needs their credentials)

## Stage 6 — AI Platform
- [ ] AI Gateway + Model Router (primary / fallback / cheap / embedding)
- [ ] Provider adapters (keys required at this point)
- [ ] Agent runtime: tool loop, per-tenant budget caps, timeouts, human fallback
- [ ] Tool policy layer → application services only (no LLM→SQL)
- [ ] Memory + Knowledge: ingestion pipeline, embedding workers, pgvector search
- [ ] Prompt registry, agent_runs / tool_calls / model_calls logging
- [ ] Usage & cost metering per tenant

## Stage 7 — Frontend (Next.js)
- [ ] Auth + tenant switcher
- [ ] Inbox: realtime (SSE/WS), assignments, AI suggestions, customer context
- [ ] Orders / Products / Inventory dashboards
- [ ] Customers, Analytics dashboards, Marketing views
- [ ] AI console (agents, prompts, usage)
- [ ] Settings: users/roles, integrations, channels
- [ ] Realtime gateway service

## Stage 8 — Marketing & Analytics
- [ ] Campaigns / ad_sets / ads management + external ad sync
- [ ] Touchpoint capture (UTM, click ids: fbclid/gclid…)
- [ ] Identity resolution → attribution (first/last touch)
- [ ] Aggregate tables + materialized views + refresh workers
- [ ] CAC / ROAS / conversion-rate / revenue-by-source endpoints
- [ ] Report workers (cold path only)

## Stage 9 — Integrations & Automation
- [ ] FastAPI worker deployment + webhook contract + service auth
- [ ] Integration workers: OAuth token refresh, provider sync
- [ ] Notifications: email / SMS / push
- [ ] Signed outbound webhooks (retried, audited)
- [ ] CRM / Sheets connectors via FastAPI workers

## Stage 10 — Billing
- [ ] Plans / subscriptions / entitlements + API-layer gating
- [ ] Usage metering (AI usage, messaging volume)
- [ ] Invoices (Stripe integration when account is ready)

## Stage 11 — Production Hardening
- [ ] OpenTelemetry: traces / metrics / logs + dashboards
- [ ] Alerts: consumer lag, DLQ depth, error rates, provider health
- [ ] Load tests on the messaging hot path
- [ ] Security pass: secret rotation, webhook signatures, WAF/CDN/TLS
- [ ] Backups / PITR + restore drill, retention & export policies
- [ ] Staging environment, Railway deployment of all services, runbooks

---

## External dependencies by stage (user-provided)

| Stage | Dependency |
|---|---|
| 0 | GitHub repo name (push approval), valid Railway token (deployment only) |
| 5 | WhatsApp Business (Meta app, phone number, tokens); later Telegram/IG/Messenger apps |
| 6 | AI provider API keys |
| 9 | SMTP / SMS provider credentials |
| 10 | Stripe account |
| 11 | Domain name, production Supabase plan, Railway token |
