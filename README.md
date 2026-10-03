# Sales OS — Conversational Commerce Platform

Multi-tenant SaaS: unified messaging (WhatsApp / Instagram / Messenger / Telegram / Webchat),
AI agents, commerce (products / inventory / orders / payments), marketing attribution,
analytics, and automation — on the production-first architecture defined in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

```
system-sales/
├── backend/          FastAPI modular monolith (Core API + Domain + Workers)
│   ├── app/
│   │   ├── core/     config, db, redis, tenancy, security, events (bus + outbox)
│   │   ├── modules/  business modules (identity, customers, conversations, catalog,
│   │   │             inventory, orders, marketing, ai, platform, billing)
│   │   └── workers/  stream worker runtime + worker pools
│   └── tests/
├── frontend/         React + Vite SPA (dashboard / inbox / channel settings)
├── infra/            docker-compose (local), deployment templates
├── docs/             ARCHITECTURE.md (canonical rules), BUILD_PLAN.md (full build map)
└── .github/          CI
```

## Golden rules (short version)

1. **PostgreSQL + Domain = the only source of truth.** LLM, Redis, and the
   frontend never own business truth.
2. **All mutations flow through Application/Domain services** — never raw SQL from
   AI or external automation tools.
3. **Events are emitted via the Outbox** inside the same transaction as the change.
4. **Redis is transport, not truth** — durable state lives in Postgres first.
5. **Tenant isolation is enforced twice**: app-layer authorization + Postgres RLS.

## Local quickstart

```bash
# 1) infra (postgres 17 + redis)
docker compose -f infra/docker-compose.yml up -d

# 2) backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp ../.env.example .env                      # adjust if needed
.venv/bin/uvicorn app.main:app --reload

# 3) health checks
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

## Status

See [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) — the full-system build map
(no feature cuts; stages are dependency order, not scope reduction).

## WhatsApp Cloud API

The WhatsApp webhook and outbound delivery run in FastAPI and its worker
runtime. Provider setup, callback address, required environment variables, and
the per-tenant integration contract are documented in
[docs/WHATSAPP_FASTAPI.md](docs/WHATSAPP_FASTAPI.md).

Telegram channel connection is verified and its webhook is registered by the
backend. Production must set `API_PUBLIC_BASE_URL` to the canonical HTTPS API
origin and `TELEGRAM_WEBHOOK_SECRET` to a 16–256-character value using only
letters, digits, `_` and `-`. The callback URL uses that configured origin
rather than a request's Host header. Existing Telegram connections created
before bot identity verification will require a one-time verification after
the migration before message reception resumes.
