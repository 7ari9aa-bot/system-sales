# Sales OS (FIHRIST): start here

Multi-tenant conversational-commerce SaaS. Customers talk to a shop over WhatsApp, Instagram,
Messenger, Telegram or web chat; an AI agent answers; staff use an inbox, a cashier (POS), and
back-office screens. This file is the fastest way to understand the repository. Read it first,
then open only the part you are changing.

## Where things live

| Path | What it is | Stack |
|---|---|---|
| `backend/` | The whole server: API, domain logic, background workers | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres 17 + pgvector, Redis |
| `frontend/` | The web app (dashboard, inbox, cashier, settings) | React 18, Vite, React Router 7, TanStack Query 5, Tailwind 4 |
| `desktop/` | Desktop wrapper app | Tauri 2, React 19 |
| `infra/` | Local `docker-compose` (Postgres, Redis) and the backend Dockerfile | |
| `docs/` | All documentation. Index: `docs/README.md` | |
| `.github/workflows/ci.yml` | What must pass: backend lint + format + tests, frontend, e2e | |

Deeper guides: [backend/AGENTS.md](backend/AGENTS.md), [frontend/AGENTS.md](frontend/AGENTS.md),
and a `README.md` inside every backend module (`backend/app/modules/<name>/README.md`).

## The rules that are never negotiable

1. **Postgres and the domain services are the only source of truth.** The LLM, Redis and the
   frontend never own business facts. Nothing writes SQL from an AI tool.
2. **Every change goes through a service.** Routers parse the request and call a service; they
   never write rows themselves.
3. **Events go through the outbox, in the same transaction as the change.**
4. **Redis is transport, not truth.** Durable state is written to Postgres first.
5. **Tenant isolation is enforced twice:** in the application layer and by Postgres row-level
   security (the `app.tenant_id` setting, bound with `bind_tenant`).
6. **Services never commit.** The caller owns the transaction; services only `flush()`.
7. **The code is the truth.** If a document and the code disagree, the code wins. Fix the document.

## How to run things

```bash
docker compose -f infra/docker-compose.yml up -d          # Postgres + Redis
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload                   # API on :8000
cd frontend && npm install && npm run dev                 # web app on :3000
```

Before you call work done, run what CI runs (details in `backend/AGENTS.md`):

```bash
cd backend
ruff check app tests scripts && ruff format --check app tests scripts
ENVIRONMENT=test pytest -q                                # needs Postgres + Redis
cd ../frontend && npm run lint && npm test
```

## Where to find a thing

| You want to change... | Look in |
|---|---|
| What the customer AI agent says or does | `backend/app/modules/ai/agents/customer/` |
| A tool the agent can call | `.../agents/customer/tools.py` (read-only tools only) |
| Cashier / POS behaviour | `backend/app/modules/pos/` and `frontend/src/cashier/` (mounted by `frontend/src/App.jsx`) |
| An HTTP endpoint | the module's `router.py` (or `routers/`), registered in `backend/app/main.py` |
| A database table | the module's `models.py`, plus a new file in `backend/migrations/versions/` |
| Background jobs | `backend/app/workers/` |
| Tenant, auth, money, events, config | `backend/app/core/` |
| A screen | `frontend/src/pages/`; shared pieces in `frontend/src/components/`; the cashier is its own app in `frontend/src/cashier/` |
| Arabic / English text | `frontend/src/lib/i18n/ar.js` and `en.js` (keep both in step) |

## Working agreements

- Arabic-first, right-to-left UI. Keep both languages working. Do not remove locale choices.
- A bug fix needs a test that fails without the fix and passes with it.
- New code must be called by something. A tested module that nothing imports is dead code.
- Do not commit credentials. The repository is public and CI scans for them.
- Dev-only helper scripts go in `backend/scripts/dev/`; documents go in `docs/` and must be
  listed in `docs/README.md`. `backend/tests/test_repo_hygiene.py` enforces both.
- Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`. Do not
  add new cross-module imports casually, and never raise the baseline without the owner's say.
