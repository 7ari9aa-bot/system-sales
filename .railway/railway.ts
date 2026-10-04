/**
 * Railway Infrastructure as Code for the Sales OS backend — replaces the root
 * `railway.json` (config-as-code, retired by Railway on 2026-12-01) and adds
 * the worker service that file could not express: one config-as-code file
 * described exactly ONE service, and the one this repo carried was the API.
 * Syntax per docs.railway.com/infrastructure-as-code (+ /reference), checked
 * against the `railway` npm SDK types (v3.12).
 *
 * Services
 * --------
 * - api     uvicorn HTTP tier. Carries the alembic pre-deploy (migrations run
 *           exactly once per deploy, from here and nowhere else) and /healthz.
 *           It must never start a worker pool itself: `--workers 2` would boot
 *           one copy per HTTP worker. Machine-checked by
 *           backend/tests/test_worker_deployment_declaration.py.
 * - workers `python -m app.workers.run` — the outbox relay plus every pool
 *           (messages, notifications, webhooks, campaigns, scheduler, jobs;
 *           run.py's no-argument default). Without it nothing consumes events:
 *           no WhatsApp messages are sent, no notifications or webhooks leave
 *           the outbox. No healthcheck (no HTTP server to probe) and no
 *           pre-deploy (two concurrent `alembic upgrade head` from api and
 *           workers deploying together would race for the migration lock).
 *
 * Why no `source` is declared
 * ---------------------------
 * Omitting it leaves each service's GitHub repo connection exactly as Railway
 * holds it; the file manages build/deploy/variables only. This is the
 * documented way to manage an already-connected service.
 *
 * Build — read before "simplifying" to a string
 * ---------------------------------------------
 * `build` is the full BuildConfig (builder + dockerfilePath), not a
 * build-command string. The Dockerfile lives at `infra/Dockerfile.backend`
 * and its COPY paths are repo-root relative (`backend/pyproject.toml`, …), so
 * the build context must stay the repo root — no `rootDirectory` on any
 * service. Known migration bug: during config-as-code → IaC migration a
 * custom Dockerfile path can be IGNORED, making Railway build from the root
 * (where no Dockerfile exists). Both keys are asserted explicitly here; after
 * cutover verify `railway config plan` shows builder DOCKERFILE + this path
 * and the first build log actually runs this Dockerfile's steps.
 *
 * Why every variable is preserve()
 * --------------------------------
 * The old railway.json carried `deploy.env` blocks of `${{...}}` mappings,
 * but `env` was never a config-as-code key — it is absent from both published
 * schemas (railway.com/railway.schema.json, railway.app/railway.schema.json)
 * and from Railway's config-as-code docs — so those blocks never reached the
 * services. The live values were always set in the Railway dashboard (or by
 * backend/scripts/deploy_railway.py). Asserting the templates as IaC literals
 * now would overwrite live values with strings the platform never applied;
 * `preserve()` instead owns the keys' existence — a variable the file does not
 * mention plans as a DESTRUCTIVE delete — while keeping every stored value.
 * The intended `${{...}}` wiring is documented in docs/RUNBOOK.md (Deploy →
 * variable mapping).
 */

import { defineRailway, preserve, project, service } from "railway/iac";

/** Build config shared by both services (same image, same repo-root context). */
const backendBuild = {
  builder: "DOCKERFILE",
  dockerfilePath: "infra/Dockerfile.backend",
} as const;

/**
 * Runtime variables both services need. Values live in Railway; carried here
 * as preserve() so the IaC plan can never propose deleting them.
 * OTEL_ENDPOINT is the raw source key the OTEL_EXPORTER_OTLP_ENDPOINT mapping
 * pointed at in the old file's `deploy.env` intent.
 */
const APP_ENV_KEYS = [
  "DATABASE_URL",
  "DATABASE_URL_ADMIN",
  "REDIS_URL",
  "SUPABASE_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "JWT_SECRET",
  "WHATSAPP_APP_SECRET",
  "OPENAI_API_KEY",
  "OTEL_EXPORTER_OTLP_ENDPOINT",
  "OTEL_ENDPOINT",
  "CORS_ORIGINS",
  "FRONTEND_PUBLIC_URL",
  "RESEND_API_KEY",
  "EMAIL_FROM",
  "EMAIL_DELIVERY_ENABLED",
  "S3_ENDPOINT",
  "S3_REGION",
  "S3_BUCKET",
  "S3_ACCESS_KEY_ID",
  "S3_SECRET_ACCESS_KEY",
  "S3_SIGNED_URL_TTL_SECONDS",
  "FEATURE_FLAGS",
  "DEBUG",
] as const;

/**
 * Staging-only raw source keys the old file's staging block mapped FROM
 * (`DATABASE_URL: ${{STAGING_DATABASE_URL}}`, …). They exist — if at all — as
 * separate dashboard variables on the staging environment; preserve() keeps
 * them from being deleted and changes nothing if they were never created.
 */
const STAGING_SOURCE_KEYS = [
  "STAGING_DATABASE_URL",
  "STAGING_DATABASE_URL_ADMIN",
  "STAGING_REDIS_URL",
  "STAGING_SUPABASE_URL",
  "STAGING_SUPABASE_ANON_KEY",
  "STAGING_SUPABASE_SERVICE_ROLE_KEY",
  "STAGING_JWT_SECRET",
  "STAGING_WHATSAPP_APP_SECRET",
  "STAGING_OPENAI_API_KEY",
  "STAGING_OTEL_ENDPOINT",
  "STAGING_CORS_ORIGINS",
  "STAGING_FRONTEND_PUBLIC_URL",
  "STAGING_RESEND_API_KEY",
  "STAGING_EMAIL_FROM",
  "STAGING_EMAIL_DELIVERY_ENABLED",
  "STAGING_S3_ENDPOINT",
  "STAGING_S3_REGION",
  "STAGING_S3_BUCKET",
  "STAGING_S3_ACCESS_KEY_ID",
  "STAGING_S3_SECRET_ACCESS_KEY",
  "STAGING_S3_SIGNED_URL_TTL_SECONDS",
] as const;

const preserveAll = (keys: readonly string[]) =>
  Object.fromEntries(keys.map((key) => [key, preserve()]));

/**
 * Per-environment preserve lists. The STAGING_* raw keys are staging-scoped:
 * Railway variables are per environment, and a preserve() of a key that does
 * not exist is a silent no-op — still, the plan reads better when production
 * carries only the keys production actually has.
 */
const preservedEnvKeys = (staging: boolean, extra: readonly string[] = []) =>
  staging ? [...APP_ENV_KEYS, ...STAGING_SOURCE_KEYS, ...extra] : [...APP_ENV_KEYS, ...extra];

export default defineRailway((ctx) => {
  const staging = ctx.isEnvironment("staging");

  const api = service("api", {
    build: backendBuild,
    start: staging
      ? // Staging runs one HTTP worker with debug logs, per the old file's
        // environments.staging override.
        "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --log-level debug"
      : "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2",
    preDeploy: "alembic upgrade head",
    healthcheck: "/healthz",
    deploy: staging
      ? { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 3 }
      : { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
    env: {
      ...preserveAll(
        preservedEnvKeys(staging, [
          // deploy_railway.py sets this on api as a staged-change marker; its
          // value is Railway's business.
          "RAILWAY_RUN_ID",
        ]),
      ),
      ENVIRONMENT: staging ? "staging" : "production",
      ...(staging && {
        FEATURE_FLAGS: "voice.enabled=false,ai.new_router.enabled=true,new_search.enabled=false",
      }),
    },
  });

  const workers = service("workers", {
    build: backendBuild,
    // No pool arguments: run.py defaults to every pool in POOLS, so a pool
    // added there deploys here without anyone editing this command — the same
    // rule infra/docker-compose.yml states for its worker service.
    start: "python -m app.workers.run",
    // Deliberately NO healthcheck (no HTTP server) and NO pre-deploy
    // (migrations belong to api, once per deploy — see the service comment).
    deploy: { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 5 },
    env: {
      ...preserveAll(preservedEnvKeys(staging)),
      ...(staging && {
        FEATURE_FLAGS: "voice.enabled=false,ai.new_router.enabled=true,new_search.enabled=false",
      }),
      ENVIRONMENT: staging ? "staging" : "production",
    },
  });

  // Project name must match the linked Railway project ("sales-os" per
  // deploy_railway.py). Environments are NOT declared: the project's
  // environment list stays dashboard-owned and plan/apply target one selected
  // environment at a time. Replicas and domains are left unmanaged (never
  // set by the old file; defaults untouched).
  return project("sales-os", { resources: [api, workers] });
});
