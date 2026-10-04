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
- Backend: Railway IaC in `.railway/railway.ts` (replaces the root
  `railway.json`, which was deleted — Railway retires config-as-code
  `railway.json`/`railway.toml` on 2026-12-01). The IaC CLI needs the SDK at
  the repo root: `npm install railway` (one time; `railway/iac` resolves
  against it). Project name in the file is `sales-os` — it must match the
  linked Railway project and the service names must match the dashboard
  (`api`, `workers`), or `railway config plan` shows unexpected creates.
- Topology — both services build the SAME image from `infra/Dockerfile.backend`
  with the repo root as build context (the Dockerfile COPYs `backend/...`, so
  no `rootDirectory` anywhere):
  - `api` — uvicorn `--workers 2` (staging: `--workers 1 --log-level debug`),
    pre-deploy `alembic upgrade head`, healthcheck `/healthz`, restart
    ON_FAILURE (production max 5, staging max 3). Migrations run ONLY here:
    once per deploy, before the new container takes traffic.
  - `workers` — `python -m app.workers.run` (no arguments = the outbox relay
    plus every pool: messages, notifications, webhooks, campaigns, scheduler,
    jobs). Without this service nothing is sent or processed — messages die in
    the outbox. No healthcheck (no HTTP server to probe) and no pre-deploy
    (two concurrent alembic runs would race). Restart ON_FAILURE max 5
    (declared; the dashboard default is ON_FAILURE max 10).
- Dockerfile-path migration bug: when Railway migrates a service from
  config-as-code to IaC, a CUSTOM dockerfilePath can be IGNORED and the build
  falls back to the repo root — where no Dockerfile exists here. The IaC
  asserts `builder: "DOCKERFILE"` + `dockerfilePath: "infra/Dockerfile.backend"`
  explicitly on both services. After the first apply, read the deploy build
  log: it must run THIS Dockerfile's steps (`pip install` from
  `backend/pyproject.toml`), not a root build.
- Variables: the IaC declares every known variable as `preserve()` — keep the
  value already stored in Railway — because the old file's `deploy.env` blocks
  were never a supported config-as-code key (absent from both published
  schemas) and never reached the services; the live values were always set in
  the dashboard or by `backend/scripts/deploy_railway.py`. A variable the IaC
  does not mention plans as a DESTRUCTIVE delete, hence the full list. The
  `${{...}}` wiring INTENT from the deleted file, for reference (never
  applied, values live in Railway):
  - staging: `DATABASE_URL` ← `STAGING_DATABASE_URL`, `DATABASE_URL_ADMIN` ←
    `STAGING_DATABASE_URL_ADMIN`, `REDIS_URL`/`SUPABASE_URL`/
    `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY`/`JWT_SECRET`/
    `WHATSAPP_APP_SECRET`/`OPENAI_API_KEY`/`CORS_ORIGINS`/
    `FRONTEND_PUBLIC_URL`/`RESEND_API_KEY`/`EMAIL_FROM`/
    `EMAIL_DELIVERY_ENABLED` and every `S3_*` ← the matching `STAGING_*` key,
    `OTEL_EXPORTER_OTLP_ENDPOINT` ← `STAGING_OTEL_ENDPOINT`;
    `FEATURE_FLAGS=voice.enabled=false,ai.new_router.enabled=true,new_search.enabled=false`.
  - production: same-key identity mappings (`JWT_SECRET` ← `JWT_SECRET`, …)
    plus `OTEL_EXPORTER_OTLP_ENDPOINT` ← `OTEL_ENDPOINT`.
- Cutover (first apply only; the repo may carry no `railway.json` while the
  services still read it — Railway blocks IaC plans for CaC-managed services):
  1. `railway link` the project; in each service's Settings confirm the config
     file path no longer points at `railway.json` (clear it if set).
  2. Select the environment, then `railway config plan`. A good plan shows
     only build/start/preDeploy/healthcheck/restart updates on api and workers
     (workers may show a `restartPolicyMaxRetries` change, 10 → 5). It must
     NOT show service deletes or variable deletes — stop and reconcile if it
     does. Repeat for the other environment, then `railway config apply`.
  3. Between the `railway.json` deletion and the apply, deploys fall back to
     each service's dashboard Settings: production settings already match the
     IaC (they were provisioned by `deploy_railway.py`), but a STAGING deploy
     in that window loses the `--workers 1 --log-level debug` override. Apply
     promptly and re-verify staging after.
- The `redis` service stays dashboard-owned and is NOT declared in the IaC:
  it is a plain `redis:7-alpine` image with a custom `requirepass`+AOF start
  command; declaring it as a Railway `redis()` database would change the
  product. Its variables (`REDIS_PASSWORD`, `REDIS_URL`) are preserved by not
  touching the service.
- Deploy order: api (its pre-deploy runs `alembic upgrade head`) -> workers ->
  frontend.

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
