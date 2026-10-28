# Sales OS — Conversational Commerce Platform

Multi-tenant SaaS: unified messaging (WhatsApp / Instagram / Messenger / Telegram / Webchat),
AI agents, commerce (products / inventory / orders / payments), marketing attribution,
analytics, and automation — on the production-first architecture defined in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

> **New to the codebase (or an AI assistant)?** Read [AGENTS.md](AGENTS.md) first. Every backend
> module also has its own `README.md`.

## Repository layout

```
system-sales/
├── backend/          FastAPI modular monolith (Core API + Domain + Workers)
│   ├── app/
│   │   ├── core/     config, db, redis, tenancy, security, events (bus + outbox)
│   │   ├── modules/  one folder per business module (see below)
│   │   └── workers/  stream worker runtime + worker pools
│   ├── migrations/   Alembic migrations
│   ├── scripts/      operational scripts; scripts/dev/ holds local-only helpers
│   └── tests/
├── frontend/         React + Vite SPA (dashboard / inbox / cashier / settings)
├── desktop/          Tauri desktop app
├── infra/            docker-compose (local), deployment templates
├── docs/             start at docs/README.md (index of every document)
└── .github/          CI
```

Backend modules (`backend/app/modules/`): `identity`, `authority`, `privacy`,
`customers`, `conversations`, `realtime`, `notifications`, `catalog`, `inventory`,
`purchasing`, `orders`, `pos` (cashier), `expenses`, `financial`, `billing`, `marketing`,
`segments`, `analytics`, `automation`, `decisions`, `effects`, `evidence`, `activity`,
`operations`, `website`, `platform`, and `ai` (agents, tools, model configs).
Imports between modules are ratcheted by `tests/test_module_boundaries.py`.

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

The documentation index is [docs/README.md](docs/README.md). The original build map is
kept for history in [docs/archive/BUILD_PLAN.md](docs/archive/BUILD_PLAN.md).

## WhatsApp Cloud API

The WhatsApp webhook and outbound delivery run in FastAPI and its worker
runtime. Provider setup, callback address, required environment variables, and
the per-tenant integration contract are documented in
[docs/archive/WHATSAPP_FASTAPI.md](docs/archive/WHATSAPP_FASTAPI.md) (and [docs/channels/whatsapp.md](docs/channels/whatsapp.md)).

Telegram channel connection is verified and its webhook is registered by the
backend. Production must set `API_PUBLIC_BASE_URL` to the canonical HTTPS API
origin and `TELEGRAM_WEBHOOK_SECRET` to a 16–256-character value using only
letters, digits, `_` and `-`. The callback URL uses that configured origin
rather than a request's Host header. Existing Telegram connections created
before bot identity verification will require a one-time verification after
the migration before message reception resumes.
