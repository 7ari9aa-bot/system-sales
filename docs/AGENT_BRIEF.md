# AGENT BRIEF — read this before touching anything

You are one of a team of agents working in this repo in parallel, in the SAME working tree.
Read this file completely first. It is the distilled experience of every previous agent that
worked here, including the mistakes.

---

## 1. What this repo is

`D:\sales system` = **Sales OS / FIHRIST** — a multi-tenant conversational-commerce SaaS.

- `backend/` FastAPI modular monolith. `app/modules/<domain>/{models,service,router}.py`.
- `frontend/` Next.js 15 / React 19 / TanStack Query v5 / Radix. Arabic-first RTL.
- `docs/` the architecture plan. The numbered spec (§n) is the source of truth for what a
  feature must do. **Grep the spec before you design.**

### Golden rules — violating one of these fails the review even if tests pass

1. **Postgres + the domain services are the only source of truth.** Every mutation goes
   through an Application/Domain service. Never write rows from a router. Never LLM→SQL.
2. **Events are emitted via the Outbox in the SAME transaction** as the mutation.
3. **Redis is transport, never truth.**
4. **Tenant isolation is enforced TWICE**: app-layer authz AND Postgres RLS via `bind_tenant`
   (the `app.tenant_id` GUC, set with `set_config(..., true)`).
5. **Services never commit.** The caller owns the transaction; services `flush()` only.
6. **`docs/` and the code disagree. The code wins** — verify every claim by reading it.

---

## 2. Environment

- Python: `backend/.venv/Scripts/python.exe` — use this EXACT path.
  Do NOT use a managed/system Python: it has none of the project's dependencies.
- Lint: `cd "D:/sales system/backend" && ./.venv/Scripts/python.exe -m ruff check app tests scripts`
  line-length 100, rules `E,F,I,UP,B`. CI enforces `ruff check`, **not** `ruff format`.
  `migrations/versions` is excluded from lint.
- One test file: `cd "D:/sales system/backend" && ENVIRONMENT=local ./.venv/Scripts/python.exe -m pytest tests/<file>.py -q`
- **There is NO local Postgres.** DB-backed tests SKIP locally with
  "no app database URL configured". CI has Postgres + Redis and runs them as the `sales_app`
  role with RLS enforced. So: write the test to run in CI, and verify locally whatever you can.
- Frontend gates: `npx tsc --noEmit`, `npm run lint`.
  `npm run build` may die with `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]` while
  cleaning `.next` — that is the sandbox shim, not a code error. Workaround:
  `mv .next .next.stale` then rebuild, then **delete `.next.stale`** (`.gitignore` only
  covers `.next/`, so a stray 236 MB dir can get swept into a commit).

---

## 3. Definition of Done — the gate, not a suggestion

1. Implemented.
2. **A test that FAILS before your change and PASSES after it.** You must actually run it in
   BOTH states and report both results. A test that cannot fail is worse than no test.
3. It must run in CI (DB-backed is fine — CI has Postgres).
4. **Not dead code.** Something in `app/` must actually call it. This repo has had SEVEN
   instances of "complete, unit-tested, and imported by nothing" — including
   `app/core/circuit_breaker.py`, `BillingSnapshotService`, and the whole ETag/If-Match
   surface. An isolated unit test on an unused module passes forever and proves nothing.

### 3a. READ THIS BEFORE WRITING A DB-BACKED TEST

**You cannot verify a DB-backed test locally. There is no local Postgres** (no docker daemon,
nothing on 5432). Such a test SKIPS with "no app database URL configured", so rule 2 above is
**impossible to satisfy for it** — and that is not a loophole, it is the trap that has already
cost this repo a multi-hour red `main`.

What actually happened: two DB-backed tests called `db.expire_all()` and then read
`tenant_ctx.tenant_id` / `invoice.id`. `expire_all()` expires every attribute, so the next access
does a lazy refresh, which in an async session raises `MissingGreenlet`. Both tests SKIPPED
locally, passed on nobody's machine, and failed only on CI — which blocked every commit stacked
on top for hours while each agent reported "passes locally".

So, for any DB-backed test you write:
- **Report it as UNVERIFIED, not as passing.** Say plainly: "DB-backed; skips locally; not
  executed." A false "passes locally" costs a whole CI cycle and hides the failure from everyone.
- **Never touch an attribute of an object bound before `expire_all()`.** Bind the scalar first:
  ```python
  invoice_id = invoice.id          # while still loaded
  db.expire_all()
  assert reread.id == invoice_id   # plain local, no lazy load
  ```
  This is enforced by `tests/test_no_expired_attribute_access.py`, which is DB-free and runs
  everywhere. It is the model to follow: **when a lesson can only be checked on CI, write a
  static guard so it is checked everywhere.**
- Prefer assertions that do not need a refreshed ORM object at all — a `SELECT` through
  `db.execute(...)` returns plain values and cannot lazy-load.


---

## 4. Hard constraints — a violation here damages everyone's work

- **Do NOT run any git write command** (`add`, `commit`, `stash`, `checkout`, `reset`).
  Leave your work in the working tree. The orchestrator commits.
- **Touch ONLY the files assigned to you.** Other agents are editing OTHER files in this same
  working tree RIGHT NOW. An out-of-scope edit will collide and can destroy their work.
  If you need a change elsewhere, **report it — do not make it.**
- Do not add dependencies.
- Do not "improve" or reformat code outside your task.

---

## 5. Report format — exactly this, max 15 lines

```
FILES: <paths you changed>
WHAT: <one line per file>
TEST: <test file + the command you ran>
BEFORE: <the exact failure you observed WITHOUT your change>
AFTER: <pass/fail>
UNVERIFIED: <what you could not check, or "none">
```

Be honest in `UNVERIFIED`. An agent that reports a false pass is worse than one that reports
nothing, because the orchestrator has to spend a full verification cycle to discover it.

---

## 6. Traps that have ACTUALLY bitten — read these twice

**The `Edit` tool intermittently reports success WITHOUT persisting the change.**
This is the NORM here, not an occasional glitch: while changing ~17 call sites in one file,
**5 separate Edits reported success and did not persist.** Always `grep` the edited region
after editing. **When a fix spans more than two or three edits in one file, rewrite the whole
file with `Write` and verify once** — the patch-and-retry loop costs more than the rewrite.
An `Edit` may also fail with `EBUSY: resource busy or locked` — that one IS retryable.

**`Edit` corrupts non-ASCII on Windows** (an em-dash was written as CP1252 `0x97`). After
editing a file containing Arabic or other non-ASCII text, validate it:
`pathlib.Path(p).read_bytes().decode("utf-8")`.

**Postgres `now()` is the TRANSACTION time.** Every row created through a service inside one
test transaction shares a timestamp, so an ordering assertion over them is meaningless —
especially when the tiebreaker is a random `uuid4` id. Make your test helper's timestamp
argument REQUIRED so the trap cannot recur by omission.

**A migration that has been APPLIED ANYWHERE IS IMMUTABLE.** Never edit an existing migration
file; always add a new one whose `down_revision` is the current head. Production is stamped, so
editing an applied revision means production never gets the column while a fresh DB does. This
has already caused one production incident here.

**`asyncpg` allows exactly ONE statement per `op.execute()`** in migrations. Need several?
Call `op.execute()` several times.

**A model that declares `server_default` promises the column may be omitted from the INSERT.**
If the database lacks that default, every insert on a NOT NULL column fails with
`NotNullViolationError`. Check the LIVE schema, not just the AST: tables whose DDL lives in a
plpgsql `DO $$ ... $$` block are invisible to AST-based migration guards.

**A route whose return type is `X | dict` is usually an error path leaking into the success
contract.** `PATCH /notifications/{id}/read` answered `200 {"detail": "not found"}` because of it.

**Never filter a paginated list client-side to answer "does X have any Y".** This repo shipped
that bug: the customer drawer fetched the 50 newest orders and filtered them in the browser, so
any customer outside that page read as "no orders". Put the filter in the SQL.

**Money aggregates use `Decimal`, never float.** Aggregate selects need an explicit
`.select_from(...)` so the FROM list is not inferred from the aggregate columns.

**i18n: every new key must be added to BOTH `ar` and `en` in `frontend/src/lib/t.ts`.**
The type is `typeof ar`, so a missing `en` key fails SILENTLY at runtime. Verify parity:
```bash
cd "D:/sales system/frontend" && "C:/Users/CS/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe" -c "
import re, pathlib, collections
txt = pathlib.Path('src/lib/t.ts').read_bytes().decode('utf-8')
c = collections.Counter(re.findall(r'^  (\w+):', txt, re.M))
print({k: n for k, n in c.items() if n != 2 and k != 'en'} or 'parity OK')
"
```

**Git Bash `/tmp` is not what Windows Python resolves.** Write scratch scripts to an explicit
path like `C:/Users/CS/AppData/Local/Temp/...`.

**bash heredocs mangle backslashes** (`"\n"` lands as `"/n"`). Prefer the Write tool.

**`zoneinfo` has no tz database on Windows** — lookups silently fall back to UTC.

**Business-hours arithmetic must use half-open intervals** `[open, close)`, or an instant
exactly on closing time loops forever.

**A predicate named `can()` must not raise.** Catch and return `False`; keep a separate
`ensure()` that raises.

---

## 7. Two classes of test — write both where they apply

- **DB-free guards** (run locally, so you can verify them yourself):
  the route is mounted in `create_app().openapi()["paths"]`, and every new query param is
  actually on the wire via `spec["paths"][path]["get"]["parameters"]`. A service can filter
  correctly while the router still ignores the argument — this test is what catches that.
- **DB-backed** (run only in CI): real behaviour, isolation, ordering, limits, cross-tenant
  refusal. Use the `db` and `tenant_ctx` fixtures from `tests/conftest.py`.

Before trusting a risky SQL statement, compile it against the Postgres dialect with no database:
```python
from sqlalchemy.dialects import postgresql
print(str(stmt.compile(dialect=postgresql.dialect())))
```
Check the generated `FROM`/`JOIN` is what you meant.

---

## 8. Verify, then report

Your summary describes what you INTENDED. The orchestrator verifies what you DID by reading
the diff. Make that cheap: keep the diff small, keep it in your assigned files, and state
plainly anything you could not verify.
