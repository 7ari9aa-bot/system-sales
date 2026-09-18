# Expert Team Roster & Battle Playbook

Ready-to-dispatch agent roles for the Sales OS build. Every lesson here was
paid for in real failures — respect it.

## Dispatch rules (hard-won)

1. **Max 2 agents in parallel.** 6 concurrent = "user concurrency limit
   exceeded" and they die mid-task (files still land — check the filesystem
   before re-dispatching).
2. **File ownership is absolute.** Each agent gets an explicit owned-files
   list and a read-only list. Concurrent agents NEVER share a writable file
   (two agents once created `app/core/errors.py` — last write won, we got
   lucky they agreed on the interface).
3. **Agents verify themselves**: every prompt ends with exact commands
   (`.venv/bin/ruff check <owned paths>` + scoped `pytest -q <owned tests>`)
   and the instruction "fix until pass". Their test reports are claims — the
   integrator re-runs the full suite.
4. **Contexts are fresh.** Every prompt must be self-contained: absolute
   paths, venv path, conventions, read-first list. Never reference "as we
   discussed".
5. **The integrator (main agent) reviews every agent file before merging**
   into the run — grep conventions (no `metadata` attr, TenantMixin first,
   no sa.Enum, tenant-leading indexes) and re-run lint/tests.
6. Bash cwd resets between tool calls — always prefix
   `cd /Users/hoadel/.zcode/workspace/default/system-sales/backend &&`.

## The roster

| # | Role | Skills loaded | Owns |
|---|---|---|---|
| 1 | **Backend Architect** (me) | everything | core/, identity/, integration review, migrations, deploy scripts |
| 2 | **Commerce Domain Expert** | SQLAlchemy 2.0, PG17 | catalog/inventory/orders services+routers |
| 3 | **Messaging Expert** | channels, webhooks, idempotency | conversations/, gateway adapters, workers |
| 4 | **AI Platform Expert** | OpenAI-compat, pgvector, agent loops | ai/ module (providers/gateway/tools/runtime/knowledge) |
| 5 | **Frontend Expert (RTL Arabic)** | rtl-arabic-frontend, ui-motion-polish | frontend/src/** |
| 6 | **Perf & Contract Expert** | web-perf-audit, contract-first-api | bundle, SW caching, OpenAPI→client codegen |
| 7 | **QA / Browser Tester** (main only) | browser-use control-browser, web-gui-tester | end-to-end UX verification with screenshots |
| 8 | **DevOps Expert** (me) | Railway GraphQL v2, Vercel API, Supabase MGMT | infra/, CI, deployments |

## Verified environment facts

### Backend
- Root: `/Users/hoadel/.zcode/workspace/default/system-sales/backend`
- Venv: `.venv` (Python 3.14) — ruff line-length 100, pytest asyncio_mode=auto
- B008 fix: `require_permission`/`Depends` in extend-immutable-calls
- Auth: JWT HS256, jti in all tokens (same-second collisions otherwise)
- Services never commit — caller owns the transaction; flush only

### Supabase (project iixxqitfopsgvaheedlg, eu-west-1)
- Pooler host is **aws-1-eu-west-1** (aws-0 dead), user `postgres.<ref>` (admin)
  / `sales_app.<ref>` (runtime, NO bypassrls)
- Migrations/ops: DATABASE_URL_ADMIN (:5432 session pooler). App/workers:
  :6543 transaction pooler → **statement_cache_size=0 required**
- Tenant GUC binding = `SELECT set_config('app.tenant_id', :tid, true)` —
  SET/SET LOCAL reject bind params
- Login/tenant discovery binds `app.user_id` BEFORE querying tenant_users;
  registration binds tenant GUC post-create; `email-validator` rejects
  `.local`/`.test` domains — demo user is `demo@salesos-demo.com`
- refresh_tokens is user-scoped (RLS-exempt); audit_logs allows NULL tenant
- Provisioning: `scripts/provision.py` (idempotent) → verify with
  `scripts/rls_smoke_test.py` (must be 7/7 PASS **as sales_app**; postgres has
  BYPASSRLS and would prove nothing)
- Test harness: conftest `db` (per-test rollback tx) + `tenant_ctx` fixtures

### Gemini (AI provider)
- OpenAI-compat base `https://generativelanguage.googleapis.com/v1beta/openai`
- Working models: **gemini-3.5-flash** (chat), **gemini-3.5-flash-lite**
  (cheap), **gemini-embedding-001** with `dimensions:1536`. gemini-2.5-* and
  3.6-flash = 404 for new accounts
- **thought_signature round-trip**: per tool_call entry
  `extra_content.google.thought_signature` must be echoed back next turn or
  the API 400s
- Provider timeout 120s + one retry on 429/502/503 (high-demand 503s happen)
- Monthly budget cap constant in gateway.py ($50), enforced pre-call

### Railway (project "sales-os", 6e5ebff6-...)
- Team-scoped token → **never query `me`**; CLI auth fails with these tokens —
  use GraphQL directly
- Variable upsert: `variableCollectionUpsert(input: {projectId,
  environmentId, serviceId, replace, variables: <JSON scalar>})`
- Settings live on **serviceInstanceUpdate** (startCommand, preDeployCommand,
  dockerfilePath, healthcheckPath) — returns Boolean, no selection
- Domains: `serviceDomainCreate(input:{serviceId, environmentId,
  targetPort})` — **Railway injects PORT=8080**; uvicorn must match (502
  otherwise). serviceDomainUpdate needs 5 required fields
- Private registry credentials = Pro plan only → deploy from **GitHub repo
  source** instead (works on trial)
- Pre-deploy: `alembic upgrade head` via preDeployCommand
- n8n: https://n8n-production-4204.up.railway.app (user=salesos /
  aZ9aAsPQuhwmhA)

### Vercel (project sales-os, prj_WKQgVoldP72yfvzhUSAloYNseCaQ)
- Env: NEXT_PUBLIC_API_URL=https://api-production-81629.up.railway.app
- CLI works with the token; env API needs `"type":"plain"`

### Frontend
- Next.js 15 + React 19, Arabic-first RTL (`dir="rtl"`, Cairo font,
  `ar-EG-u-nu-latn` numerals, `dir="ltr"` islands for emails/URLs/IDs)
- api.ts: localStorage tokens + refresh-on-401 + Arabic error messages
- Motion rules: transform/opacity only, ≤400ms, one easing family
  `cubic-bezier(.2,.8,.2,1)`, prefers-reduced-motion mandatory
- Perf: self-host fonts if possible, route-prefetch on hover, lazy heavy
  pages; never cache-first HTML or /api/*

## Standing verification gate (every merge)

```bash
cd backend && .venv/bin/ruff check app tests scripts
.venv/bin/python -m pytest tests -q          # currently 126 passing
cd ../frontend && npm run build              # 14 routes
cd ../backend && .venv/bin/python scripts/rls_smoke_test.py   # 7/7 PASS
```

## Live URLs

| What | URL |
|---|---|
| Dashboard | https://sales-os-three-bay.vercel.app |
| API | https://api-production-81629.up.railway.app |
| n8n | https://n8n-production-4204.up.railway.app |
| Demo login | demo@salesos-demo.com / Demo-1234 |
