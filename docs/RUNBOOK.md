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
# Automated local database spin-up and verification (pgvector + redis + migrations + seeds + RLS smoke):
.venv/bin/python scripts/dev_db.py

# Or individually:
.venv/bin/python scripts/provision.py   # app role + RLS policies + seeds
.venv/bin/python scripts/rls_smoke_test.py  # exit 0 and every verdict line reads [PASS]
```

## Backups & DR

- Supabase daily backups + PITR (enable in project settings; production plan).
- Quarterly restore drill: restore a backup to a scratch project, run
  `scripts/rls_smoke_test.py` + `pytest -q` against it, verify tenant counts
  per `tenants` vs `customers` sample. Automated via:
  `.venv/bin/python scripts/restore_drill.py --target-url <POSTGRES_URL>`
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
- HTTP 5xx rate > 2% for 5 min (needs the metrics backend — R-F2; the script
  below covers the live invariants and the `/readyz` probe, not the rate).
- Monitor the live invariants automatically:
  `.venv/bin/python scripts/monitor_alerts.py`

## Canonical agent prompts (why a code change is not enough)

`agents.system_prompt` is written ONLY when the agent row is created
(`core/provisioning.py`); re-provisioning re-syncs tools, never the prompt. So a
prompt fix in `agents/<kind>/definition.py` does NOT reach existing agent rows —
and `POST /ai/agents/{id}/publish` snapshots the ROW, so a new version would carry
the old text. Editing the file and publishing are both necessary and neither is
sufficient.

Reconcile the rows, then snapshot and pin them (dry run first — it is a dry run by
default, and it refuses a non-local database without `--allow-remote`):

```bash
.venv/bin/python scripts/sync_canonical_agent_prompts.py                 # dry run, shows the diff
.venv/bin/python scripts/sync_canonical_agent_prompts.py --apply --publish --allow-remote
```

`--publish` mints an immutable version from the corrected row and lets the publish
path create the stable `agent_deployments` row when none exists. Until that row
exists the runtime serves the agent's MUTABLE settings, so a published version
with no deployment is a snapshot nobody serves.

### No database DSN? The management-token path

Where only a Supabase management token exists (it never returns the database
password — the connection string comes back with the literal placeholder
`[YOUR-PASSWORD]`), the same reconcile runs through the project's SQL endpoint:

```bash
export SUPABASE_ACCESS_TOKEN=sbp_...
.venv/bin/python scripts/reconcile_prod_agent_prompts.py --ref <project-ref>          # dry run
.venv/bin/python scripts/reconcile_prod_agent_prompts.py --ref <ref> --apply
```

One atomic statement: the row, an immutable version (`max+1`), and the stable
deployment pointer move together or not at all. An agent whose deployment is
mid-canary is skipped and reported; `--force` is required to touch an agent whose
prompt is not the known stale canonical text, because a store that edited its
prompt on purpose must not be silently overwritten.

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

## Voice & customer photos — the switches (customer agent)

Both features are built and fail CLOSED on a missing credential. At startup the
API now logs a WARNING per dark feature (`ai.readiness`) naming the exact env
var — grep Railway logs for `multimodal_readiness` after any deploy.

**Voice-in (customer sends a note, agent answers in TEXT):**

Preferred (owner design): Qwen Omni receives the audio directly, with no separate STT model and no TTS:
```
AI_VOICE_AUDIO_INPUT=true
AI_VOICE_MODEL_ALIAS=omni
```
The tenant must have a `model_configs` row for alias `omni` pointing to an Omni endpoint that accepts
`input_audio` (the Vercel AI Gateway currently rejects this content part; the tested direct DashScope
INTL endpoint accepts WAV and OGG base64). The audio attachment must pass the ClamAV scan first; only
then are its durable bytes read from Supabase and sent as a data URL. Unknown audio formats, missing
scanner verdicts, storage errors and Omni budget fallback do not send the bytes: the customer is asked
to type or is handed to a human. Audio egress is therefore behind the same malware verdict as images.

Legacy fallback if direct Omni is disabled:
```
AI_STT_API_KEY=<key>          # whisper-1; AI_STT_MODEL/AI_STT_BASE_URL optional
```
Budget is reserved before a Whisper call. TTS is deliberately UNWIRED (replies are text) — `AI_TTS_*`
enables a future feature only.

**Photos-in (customer sends a photo, agent matches it to the catalog):**
```
MEDIA_SCANNER_HOST=<clamd host>   MEDIA_SCANNER_PORT=3310   # clamav/clamav beside the API
AI_EMBEDDING_VISION_API_KEY=<dashscope key>                  # tongyi-embedding-vision-flash
AI_RERANKER_API_KEY=<jina key>                               # jina-reranker-m0
```
Then INDEX the catalog once (and after catalog changes):
`.venv/bin/python scripts/index_product_images.py`
Without the scanner the ADR-062 gate never mints a URL and vision never runs —
photos are acknowledged, not analyzed. A scanner without the two provider keys
scans photos and STILL never matches; the readiness warning names that trap.

**Quality (spec §12.2/§23.7):** the decision thresholds are documented
PLACEHOLDERS (high_floor 0.62, gap_min 0.04, rerank_floor 0.45) pending a
labelled corpus run (200-500 real photos incl. out-of-catalog). The design
degrades toward "present with uncertainty, never a confident wrong match":
a dead reranker can never yield HIGH, and only sellable, in-stock products
verify. Calibration is a config change (`VisionThresholds`), not a code one.
