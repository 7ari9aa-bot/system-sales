# Operations Runbook

## Environments

| Env        | DB                                   | Redis                  | Deploy target |
|------------|--------------------------------------|------------------------|---------------|
| local      | docker-compose pgvector (pg 17)      | docker-compose redis 7 | uvicorn       |
| production | Supabase `iixxqitfopsgvaheedlg` (eu-west-1) | Railway Redis (SEPARATE instances for cache vs streams) | Railway |

## Deploy

- Frontend: Vercel via the dashboard (Root Directory = `frontend`). The
  `/api/v1` → Railway rewrites live in `frontend/vercel.json` — changing the
  backend domain means updating that file, and it deploys with the next push.
- Backend: Railway from the root `railway.json` (Dockerfile build + uvicorn
  start command, `/healthz` healthcheck, ON_FAILURE restart policy).
- Deploy order: migrate job (`alembic upgrade head`) -> api -> workers -> frontend.

## Database roles

- `postgres` (Supabase, BYPASSRLS): migrations, provisioning, ops scripts ONLY.
- `sales_app` (no bypassrls): API + workers runtime. RLS binds it via the
  `app.tenant_id` / `app.user_id` GUCs set per transaction (`bind_tenant`).

## Migrations

```bash
cd backend
DATABASE_URL_ADMIN=... .venv/bin/alembic upgrade head
```

- Alembic uses `DATABASE_URL_ADMIN` (session pooler :5432). Never run DDL over
  the transaction pooler (:6543).
- Data migrations touching tenant tables must `SET app.tenant_id` first (RLS is
  FORCED, even for the owner — BYPASSRLS exempts postgres only).

## Provisioning (idempotent)

```bash
.venv/bin/python scripts/provision.py   # app role + RLS policies + seeds
.venv/bin/python scripts/rls_smoke_test.py  # must print 7/7 PASS
```

## Backups & DR

- Supabase daily backups + PITR (enable in project settings; production plan).
- Quarterly restore drill: restore a backup to a scratch project, run
  `scripts/rls_smoke_test.py` + `pytest -q` against it, verify tenant counts
  per `tenants` vs `customers` sample.
- Redis is transport-only, but a full Redis loss also removes entries whose
  outbox rows already reached `published`. Pending/failed rows are retried by
  the normal relay; published-but-unprocessed entries require the explicit
  recovery command below. The recovery command previews by default and uses
  `processed_events` plus the original outbox id to avoid replaying completed
  work. For legacy `message.outbound` rows without a stable id, it uses the
  outbox row id; other legacy events without a stable id are excluded. Do not
  run it while consumers are active: replaying `message.events` can resume
  queued customer messages.
- After a Redis region move or full data loss: stop the worker consumers, run
  `python -m app.workers.replay_outbox --stream message.events` to review the
  eligible count, then run the same command with `--execute` only when resuming
  the queued work is intended. Repeat for other supported streams as needed;
  restart workers only after replay completes. Keep published outbox rows until
  replay history has a complete, tested retention/recovery lifecycle.
- Before relocating Railway services, inventory persistent state and take
  restorable backups. The current Redis service has no attached volume, so
  changing its region loses its local AOF/RDB files; follow the outbox recovery
  procedure above after the replacement Redis is ready. Keep API and worker
  regions aligned with Redis, then verify database connectivity, health checks,
  and public domains after cutover.
- DLQ inspection: `python -m app.workers.inspector list <stream>.dlq` /
  `requeue <stream> <entry_id>`.

## Alerts (minimum viable)

- `readyz` 503 (database/redis check) — page.
- Outbox oldest pending row age > 5 min — relay stuck.
- Redis consumer group lag on `message.events` > 1000 — scale message workers.
- DLQ depth > 0 for > 1h — on-call review.
- HTTP 5xx rate > 2% for 5 min.

## Scaling order (when pressure rises)

1. Message workers (hot path first — never let AI load squeeze messages).
2. API replicas (stateless).
3. Supabase: read replicas for analytics; move BI to the event pipeline.
4. AI workers separate deployment when AI latency/budget spikes.

## Secret rotation

- JWT_SECRET rotation: dual-key verify window (Stage: rotate with overlap).
- Provider tokens live in `integrations.credentials` — encrypt at rest before
  storing production WhatsApp tokens (Stage 11 hardening item).
- Rotate `sales_app` password via `scripts/provision.py` (rewrites .env DSNs).
