# Backend guide

FastAPI modular monolith. Read the root [AGENTS.md](../AGENTS.md) first for the rules and the
map of the whole repository. This file covers the backend only.

## Layout

```
backend/
├── app/
│   ├── main.py          builds the app and registers every router
│   ├── core/            shared plumbing: config, db, tenancy, security, events/outbox, money,
│   │                    rate limits, secrets, storage. No business rules live here.
│   ├── modules/<name>/  one folder per business area (list in the root README)
│   └── workers/         background processes: message, campaign, POS, scheduler, retention
├── migrations/versions/ Alembic migrations (do not hand-format; excluded from lint)
├── scripts/             operational scripts; scripts/dev/ is for local-only helpers
└── tests/               one file per behaviour; subfolders: agent_eval, dr, gate, perf, security
```

### Shape of a module

A small module is `models.py` (tables), `service.py` (the rules), `router.py` (HTTP), and
sometimes `schemas.py`. A bigger one splits `service.py` into a `services/` package and
`router.py` into `routers/`. The flow is always:

```
router  -> parses + authorises the request, calls a service
service -> applies the rules, writes through models, emits outbox events, flush() only
model   -> SQLAlchemy table; every tenant table has row-level security
```

Each module has its own `README.md` saying what it owns and what it must not do.

## Commands

CI runs exactly these, against Postgres 17 (pgvector) and Redis 7:

```bash
ruff check app tests scripts
ruff format --check app tests scripts      # the tree is formatted; keep it that way
alembic upgrade head
python scripts/provision.py                # roles, RLS policies, seed data (idempotent)
pytest -q
```

Settings: line length 100, rules `E,F,I,UP,B`, Python 3.12, `asyncio_mode = auto`. The live-model
evaluation costs money and only runs with `-m live_eval`.

Bring up the databases with `docker compose -f ../infra/docker-compose.yml up -d`. Tests need
`DATABASE_URL`, `DATABASE_URL_APP` and `DATABASE_URL_APP_ADMIN` pointing at the `sales_app`
role (not `postgres`, which bypasses row-level security and would hide isolation bugs). The
exact values CI uses are in `.github/workflows/ci.yml`.

## Tests: the trap to avoid

Database-backed tests **skip silently** when no database is configured
("no app database URL configured"). A skipped test passed nothing. If you could not run a
database test, say it was **not executed**; never report it as passing.

Do not read an attribute of an ORM object after `db.expire_all()`: in an async session that
raises `MissingGreenlet`. Copy the value into a plain variable first.
`tests/test_no_expired_attribute_access.py` enforces this everywhere without a database. When a
lesson can only be checked on CI, write a static test like that one so it is checked everywhere.

A fix needs a test that fails before it and passes after. A new module needs a caller.

## Guard tests worth knowing

| Test | Protects |
|---|---|
| `test_module_boundaries.py` | Cross-module imports are ratcheted. Do not raise the baseline. |
| `test_no_committed_secrets.py` | No credentials in the public repo. |
| `test_repo_hygiene.py` | Docs are indexed, scripts are in `scripts/`, README names every module. |
| `test_no_expired_attribute_access.py` | The `MissingGreenlet` trap above. |

## Dev helpers

`scripts/dev/run_gate.sh` runs pytest with CI-like settings against a local database.
`scripts/dev/run_deep_crawl.sh` crawls every UI route. Both find their own folder, so run them
from anywhere. `scripts/seed_demo.py` creates a demo tenant through the real services.
