# Fihrist Desktop — review of the proposed architecture

Reviewed: 2026-09-25, against the tree at `w4-t3-money` (head `175ff5c`).
Source under review: "LEAD ENGINE DESKTOP — Final Production Architecture + Agent Build
Constitution" (79 sections), received as an attachment.

Verdict: **adopt it, with six conflicts resolved first.** The bones — Tauri 2 + Vite +
React SPA, server-authoritative business rules, contract-first client, SQLite as a read
model and never a system of record, deny-by-default capabilities, no secrets in the
binary — are the same conclusions this repository reached from its own audit, and they
fit Fihrist's backend as it stands today. The conflicts below are all cases where the
document describes a platform we do not have yet, or restarts a convention we already
settled. Nothing in it argues for changing the web app.

Naming: the product is **Fihrist**. Every `LEAD ENGINE` / `lead-engine` / `leadengine://`
in the document becomes `Fihrist` / `fihrist` / `fihrist://` (bundle id
`com.fihrist.desktop`, updater channel ids, tray labels, deep-link scheme). The web app
already carries that identity (`FihristProvider`, the `fh-` CSS prefix), so the document's
title is the only thing that has to move.

---

## 1. What already agrees, verified against the tree

| Document claim | Fihrist today | Evidence |
|---|---|---|
| §7 "backend owns the contract, generate from OpenAPI" | FastAPI is the composition root; the whole current wave is adding `response_model` to routes that had none | `backend/app/modules/*/router.py`; `docs/GAP_REGISTER.md` line P8 |
| §60 structured errors `{code, message, retryable, request_id}` | Exactly the v2 error envelope, already enforced by a gate that refuses hand-built error bodies | `backend/app/core/errors.py::build_error_envelope`, `backend/tests/test_error_contract.py` |
| §25 optimistic concurrency (version / ETag / If-Match) | Shipped: `If-Match` + strong ETag across versioned entities, CAS in one statement, 409 on loss | `backend/app/core/idempotency.py::apply_versioned_update` |
| §24 idempotent mutation queue keyed by `idempotency_key` | Middleware exists, **fails closed**: 503 when its store is unreachable, 409 on reuse-with-different-body, in-progress, or a previous unknown outcome | `backend/app/core/idempotency.py` |
| §12/§50 desktop never re-implements business rules | The spec says the same (§55 "no business aggregation in the browser") and the frontend is audited against it | `docs/GAP_REGISTER.md` §55 close-outs |
| §73 same data / same permissions, different composition | RBAC permission codes on every route (`settings:write`, `pii:read`, …) and per-tenant isolation in the DB | `require_permission`, FORCE RLS + `app.tenant_id` GUC |
| §2 React 19 / TanStack Query v5 | Web is React 19.0 + TanStack Query 5.103 + Next 15 — same majors, so nothing forks on version lines | `frontend/package.json` |
| §17 never store tokens in `localStorage` | Noted as a **web** trade-off, not a desktop one: the browser build keeps `sales_os_tokens` behind a hardened reader. Desktop must not copy that reader — `src/lib/api.ts` is web-only by design | `frontend/src/lib/api.ts::getTokens` |

The last row is the one worth restating to the desktop team as law: **the web client's
storage layer is not reusable**, and `localStorage`/`sessionStorage` do not exist in a
Tauri webview anyway. Everything else in the SDK is shareable in spirit.

---

## 2. The six conflicts, and how each gets resolved

### C-D1 — Repository shape (§64): no `apps/web` restructure

The document's `lead-engine/apps/{web,desktop}` + `packages/*` layout does not describe
this repository, which is `backend/` + `frontend/` + `docs/` at the root, with every CI
path, import alias (`@/…`) and deploy config written against that.

Decision: desktop lands at **`desktop/`** — sibling of `frontend/`, its own
`package.json`, `tsconfig`, `src-tauri/` and its own CI job gated by `paths:`. It never
imports from `frontend/` and `frontend/` never imports from it.
Rejected: moving the web app into `apps/web` — a rename-only change of every path in the
app I am actively hardening, for zero product gain.

`packages/*` is deferred, not refused. The moment a second consumer genuinely needs a
shared module it gets extracted once, into `packages/<name>`, from a real duplicate —
not before. Two of the nine proposed packages would today contain exactly one consumer.

### C-D2 — Contract generation depends on my current wave

§7's pipeline (FastAPI → OpenAPI → generated types) only works on routes that declare a
response model. Counted against the live application with `create_app().openapi()` — 245 operations,
**112 publish a 2xx JSON schema, 133 publish none.**

The two figures this document carried before ("175 of 185" here, "~45 of 62" in the register's P8
line) were grep counts over lines starting `@router.` in `app/modules/*/router.py`, and they were
wrong in two directions. **Only 186 of the 242 route decorators in `backend/app` are named
`@router`** — the other 56 sit on `@tenants_router`, `@templates_router`, `@hierarchy_router`,
`@sla_router`, `@billing_router`, `@platform_router`, `@analytics_router`, `@webhook_router`,
`@search_router` and `@public_router`, in files and under names the pattern never looked at. And the
pattern counted only `response_model=` on the decorator line, while FastAPI also types a route from
its return annotation (`-> TaskMutationResult`), which is how `operations` reads as 10 typed to a
grep and 20 typed in the published document.

The desktop session's count (245 operations, 82 typed, §6.1) and mine (245, 112) agree on the
denominator and disagree on the numerator for that same reason: it counted the decorator argument,
this counted what OpenAPI publishes. The published schema is what a generator sees, so **112 typed /
133 untyped of 245** is the number to use — and it should be re-derived from
`create_app().openapi()` with the routers flattened, never from a filename pattern.

Generating a client now still produces `any` across the majority of the surface, which §7 forbids.

Decision: `desktop/openapi.lock.json` holds a pinned export of the spec plus its
SHA-256. A CI job regenerates it and fails on drift, and a second check refuses generated
models containing `any` for endpoints the desktop consumes. The desktop team starts on
Foundation (§68 Phase 0) while this wave lands route families in batches; the pin is
what lets both move without waiting on each other.

### C-D3 — Realtime is SSE here, not WebSocket (§19/§20)

The document draws `Realtime Gateway → WebSocket`. Fihrist exposes **two SSE endpoints**
and no WebSocket server: `/api/v1/realtime/stream` and the conversations stream
(`text/event-stream`, `backend/app/modules/realtime/router.py:406`,
`backend/app/modules/conversations/router.py:688`). Register line P9 already records the
real gaps: two dialects, no `Last-Event-ID`, and free-text filters that answer 200 with
nothing.

Decision: **build the desktop event plane on SSE**, because §20's actual requirements —
reconnect, backoff, heartbeat, cursor, gap detection, resync — are transport-agnostic and
SSE carries them with the auth we already have. A WebSocket gateway stays a separate ADR
with a cost line (new backend surface, Railway connection handling, worker fan-out), and
is not a prerequisite for any desktop phase.

Hard dependency the other way: the desktop's `sync_cursors` design (§22) cannot be honest
until `Last-Event-ID` / cursor replay exists server-side. That item is on my list (P9);
until it lands, the desktop must resync by re-querying, and its `Gap Detection` state must
say so rather than silently replaying nothing.

### C-D4 — Authentication (§17): no OAuth/PKCE endpoint exists

The document's flow — system browser → OAuth/PKCE → deep-link callback — is not
implementable today: there is no authorization server in the repo. The real surface is
`POST /auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/switch-tenant`,
`/auth/mfa/*` (`backend/app/modules/identity/router.py:88-214`), returning a
`TokenPair` for Bearer use. Grep for `pkce|code_verifier|authorization_code` returns
nothing.

Decision (Option A, recommended): keep the password + MFA flow, and satisfy §17's real
requirement instead of its mechanism —

- access token: **memory only** (Rust-side state, never `localStorage`, never SQLite);
- refresh token: **Stronghold** vault, one vault per OS user, wiped on logout;
- `fihrist://auth` deep link retained for SSO later, and single-instance kept regardless
  (it owns "second launch focuses the window", which is wanted now);
- `/auth/switch-tenant` is the multi-tenant story, and it must invalidate every cached
  query and every SQLite row on switch — a leaked cross-tenant cache is the worst thing a
  desktop build can do, and it is the one place RLS cannot save the client.

Option B (add a real PKCE authorization code flow server-side) stays available; it is a
backend workstream of its own and nothing in phases 0–3 depends on it.

### C-D5 — Search (§33): there is no OpenSearch

`Desktop → Search API → OpenSearch` names a service this project does not run and has no
credential for. Search today is escaped `ILIKE` (`A7`), and real Postgres full-text
(`tsvector` + GIN over `customers`, `products`, `knowledge_items`, `simple` config because
content is Arabic and Latin together) is **landing in this very wave**.

Decision: the desktop calls the same `GET /search` the web app calls, and the local half
of §33 is SQLite FTS on the cached rows for instant keystroke response — which is what a
desktop is genuinely better at than a browser. Adopting an external search engine is a
separate ADR with an external-dependency cost, exactly the class of decision the register
keeps out of internal waves.

### C-D6 — ADR numbering collides with the existing register (§65)

`ADR-001 … ADR-015` restarts a sequence this repository already filled: `docs/adrs/` holds
numbered ADRs from `ADR-001-to-004.md` through `ADR-026-to-041.md`, plus per-file ADRs
(`ADR-013-tenant-context-execution-modes.md`, `ADR-015-event-consumer-idempotency.md`,
`ADR-058` cited in `backend/app/workers/base.py`). Two ADR-005 meaning two different
things in one repo is how governance becomes decoration.

Decision: desktop ADRs continue the existing sequence (next free number, verified with
`ls docs/adrs/` at write time) and one document per number, and the fifteen proposed
titles are kept as a checklist, not as ids. Several are already answered by existing
ADRs — tenancy (§151 chain), consumer idempotency (ADR-015), execution modes (ADR-013) —
and must cite them rather than restate them.

---

## 3. Where the document is silent and Fihrist is not

Rules a second client has to inherit, none of which the constitution mentions:

1. **Money is a string on the wire.** Decimal columns leave as strings; a client that
   parses to float re-creates the bug this repo spent a wave deleting (T5, T6). Contract
   tests refuse a numeric money field; generated TS types must stay `string`.
2. **Arabic-first, RTL.** The web product is RTL by default with a language toggle, and
   digit formatting is deliberately locale-specific (§F13). A desktop that hard-codes LTR
   or Latin digits is a regression against the product, not a free choice.
3. **Tenancy is never a parameter.** `test_no_route_lets_the_client_name_a_tenant` pins
   that: the tenant belongs to the credential. The desktop's workspace switcher is a call
   to `/auth/switch-tenant`, never a header the UI invents.
4. **PII redaction is server-side.** `pii:read` decides what a body contains; a desktop
   cache that stores "what the API said" must store it per actor and drop it on logout, or
   it becomes an unredacted copy of customer data on a laptop.
5. **Every release needs signing, notarization and an updater key** (§56/§57) — these are
   external credentials. They are gates, not tasks: nothing in phases 0–4 blocks on them,
   and no key material or token value goes into this repository (project rule already).
6. **Localisation of failures.** The v2 envelope's `retryable` and `code` are what the UI
   branches on; the desktop must not branch on `message` text.

---

## 4. Team boundary — the file rule that keeps the two teams out of each other's way

| Team | Writes | Never writes |
|---|---|---|
| Web/API (current) | `backend/**`, `frontend/**`, `docs/**`, `.github/workflows/ci.yml` | `desktop/**` |
| Desktop | `desktop/**`, its own workflow file `.github/workflows/desktop-ci.yml`, new ADR files under `docs/adrs/` | `backend/**`, `frontend/**`, existing ADR files |

Crossings are requests, not edits. If the desktop team needs a field, a route or a status
code that does not exist, it files the gap in `docs/DESKTOP_ARCH_REVIEW.md` §5 (append a
row) and I land it in the API wave — that keeps the OpenAPI document honest and keeps one
pair of hands on the contract. The one file both teams may touch is this review document,
append-only, under a `## 5. Requests to the API team` table.

Two shared-infra hazards to respect: the desktop CI needs Windows and macOS runners
(this project's CI is Ubuntu-only today), and its builds cannot be verified on the
current Linux-only job. Neither is a blocker for phases 0–3, both are budget questions
before phase 5.

---

## 5. Execution order I endorse (and the two I would move)

Phases 0–3 as written (§68) are right, and Phase 0's "no features" is the discipline that
makes the rest cheap. Two changes:

1. **Move the SQLite/offline queue (Phase 3) behind a decision.** Offline-tolerant *reads*
   are cheap and worth having early. An offline **mutation** queue (§24) is a
   product-policy decision about which writes may be deferred, and it depends on
   per-route `Idempotency-Key` coverage that exists only partially today. Do reads first,
   and treat queued mutations as its own ADR after the gap list in §3.1 is settled.
2. **Pin the toolchain before writing code.** §2 fixes Tauri 2.11.5 / CLI 2.11.4 / Vite
   8.1 / React 19.3, which I have not re-verified against the registries in this session;
   the "no floating `latest` in CI" rule in the same section is the one that matters, so
   the first commit should be a lockfile plus a `rust-toolchain.toml`, and versions
   corrected in it rather than in prose.

---

## 6. Requests to the API team (desktop → Session A) — append-only

Added by the desktop session on 2026-09-25, per §4. §4 promises this table under a
`## 5. Requests to the API team` heading; §5 was taken by the execution order, so it
is §6. Every row names the evidence in the current tree, not an assumption.

| # | Endpoint / artifact | What is needed | Justification | Blocked desktop work |
|---|---|---|---|---|
| R1 | `desktop/openapi.lock.json` | A pinned OpenAPI export + SHA-256 produced by a job on the API side, and a drift check. No generator exists today: `backend/scripts/` has no OpenAPI export (0 matches for `openapi` in `*.py` there) and `ci.yml` has no such step | C-D2 | Phase 1 contract tests; the "generated `any` fails CI" rule cannot be enforced without an input |
| R2 | the `IDEMPOTENT_PATHS` prefixes | A machine-readable per-operation idempotency marker in the OpenAPI document, plus `Idempotency-Replayed` declared as a response header | `backend/app/core/idempotency.py:117-128` — the allow-list is 7 prefixes (`/orders`, `/billing`, `/marketing/campaigns`, `/marketing/touchpoints`, `/conversations`, `/privacy/data-requests`, `/workflows/executions`), and a replay is already distinguishable by header | Phase 3 offline-mutation ADR: which writes may be deferred, and how a queued attempt learns it was a replay |
| R3 | `GET /api/v1/search` | Route `SearchPort` through the `tsvector` columns that now exist, add `entity_type` filter + rank ordering + cursor paging | `backend/app/core/search.py:57` says out loud that this is *not* full-text ("no tsvector"); the generated columns are in `ai/models.py:179-186` and `catalog/models.py:79-87`; the route is `operations/router.py:53,147` with `response_model=list[SearchHit]` | Phase 4 ⌘K and inbox search parity; today local SQLite FTS is the fast path by necessity, not by preference |
| R4 | `GET /api/v1/realtime/stream` | `Last-Event-ID` / cursor replay (register line P9) | C-D3's stated hard dependency | Honest gap detection. Until then the event plane re-queries and says so, which is the behaviour Phase 1 will ship |
| R5 | realtime auth dependency | A short-lived stream-scoped credential instead of the long-lived access token accepted in `?token=` | `backend/app/modules/realtime/router.py:51-59`, and `:61-65` noting a removed user kept the firehose "for the whole token lifetime" | Nothing functionally — the desktop sends a header from Rust (ADR-059). This is a security request, and it is the web client's exposure too |
| R6 | error contract | A published list of `error.code` values with their `retryable` mapping (an enum in the OpenAPI components, or a doc both clients read) | §3.1 and §4.5: the UI branches on `code`, so the code set is part of the contract | Phase 1 error mapping is today a per-case guess; every feature's error state inherits that guess |
| R7 | versioned entities | Which routes return a strong `ETag` and accept `If-Match`, stated per route | `backend/app/core/idempotency.py:684-767` shows the mechanism; only reading the source reveals which entities are versioned | Phase 4 optimistic UI reconciliation |
| R8 | `GET /auth/me` | The actor's resolved permission codes (`pii:read`, `settings:write`, …) beside `role_code` | `backend/app/modules/identity/router.py:113-129` returns `id/email/full_name/is_platform_admin/tenants[]{id,name,slug,role_code}` — no permission set | A deny-by-default UI has to hide affordances it cannot yet enumerate; today the client would have to invent the mapping |

### 6.1 Measurements that have moved since this review was written

* **Route coverage.** "175 of 185 routes declare no `response_model`" and the
  register's older "~45 of 62" (`docs/GAP_REGISTER.md:431`) both disagree with the
  tree as counted on 2026-09-25: **245 route decorators, 82 with `response_model`,
  163 without** (per module: `platform` 29/29, `operations` 20/20, `segments` 6/6,
  `identity` 21/32, `customers` 5/19, `marketing` 1/17, `ai` 0/24,
  `conversations` 0/22, `catalog` 0/18, `orders` 0/15). Method: every
  `@router.{get,post,put,patch,delete}` decorator under `backend/app`, checked for
  `response_model` in its own decorator block. The conclusion of C-D2 is unchanged;
  the number wants a script that reads `app.openapi()` so the three figures stop
  drifting apart.
* **`/auth/switch-tenant` takes `tenant_id` as a query parameter**
  (`identity/router.py:132-135`), while the guard named in §3.3
  (`tests/test_automation_routes.py:205-213`) asserts `PREFIX = "/api/v1/automation"`
  only — so the invariant "a tenant is never a parameter" is pinned in one slice of
  the surface, not on `/auth`. Reported, not fixed; the desktop treats `tenant_id`
  as an opaque id copied from `/auth/me` and never as input.
* **Refresh tokens rotate, and reuse of a revoked token revokes the whole family**
  (`backend/app/modules/identity/service.py:383-399`). C-D4's token design is right,
  and this raises the stakes: two windows refreshing from a stale vault copy log the
  user out everywhere, so Phase 1's Stronghold access needs a single-flight refresh
  across windows and processes, not a per-window one.
* **No WebSocket, no PKCE, no OpenSearch: confirmed still true.** Grep over
  `backend/app` returns 0 hits for `websocket`, 0 for
  `pkce|code_verifier|authorization_code`, and the only `text/event-stream` routes
  are the two named in C-D3 (`realtime/router.py:406`, `conversations/router.py:688`).
* **Toolchain versions in §2 of the original doc.** Resolved against the registries
  on 2026-09-25 and pinned in `desktop/package.json` + `desktop/rust-toolchain.toml`:
  Tauri crate 2.11.6 / CLI 2.11.5 / api 2.11.1, Vite 8.3.1, React 19.3.0,
  TanStack Query 5.103.2, Rust stable 1.98.1 (Tauri's MSRV is 1.77.2). One real
  correction: **TypeScript is pinned to 5.9.3, not `latest` (7.0.2)**, because
  `typescript-eslint` 8.70.1 declares `>=4.8.4 <6.1.0` — TS 7 would take the type-aware
  boundary lint away.


## 7. Session A's answers to the Phase 0 report's open items (2026-09-25)

The Phase 0 gates were re-run from `desktop/` on Session A's machine before any of this
was committed: **110/110 tests, `tsc` clean, build clean, hardcoded-host check OK** —
the §6.5 precondition is met. What remains unverified is unchanged from the report's own
§4: the entire `src-tauri/` tree (no `cargo` on any machine yet) waits for the first
`desktop-ci.yml` run, and no `Cargo.lock` exists until CI generates one.

1. **Runner budget** — `ci.yml` stays unfiltered for now: the backend suite is the
   project's only DB-backed executor and it must run on every API-affecting push. The
   desktop work is already isolated by `desktop-ci.yml`'s `paths:` filter. Revisit if a
   desktop-only push burns meaningful minutes.
2. **ADR-059 / CORS** — confirmed: no `tauri://localhost` or `http://tauri.localhost`
   entry is to be added to `CORS_ORIGINS`. The desktop is not a browser origin; it
   authenticates as a client, not as a page.
3. **Canonical ADR directory** — **`docs/adrs/` (one file per number) is canonical**;
   every ADR from 042 on lives there and new ones land there. `docs/adr/`'s five
   range-compilation files are a frozen archive of 001–041 and will not be extended.
4. **R1 is accepted as the critical path** and is queued behind the current CI-repair
   wave: a script exporting `create_app().openapi()` to `desktop/openapi.lock.json`
   with its SHA-256, plus the drift job. The other requests (R2–R8) follow.
5. The §5 defects are registered on the API side: `?token=` on the realtime stream
   (R5, web exposure too) and `tenant_id` as a query parameter on
   `/auth/switch-tenant` are both scheduled; the route-coverage figures were already
   reconciled to the measured 245/112/133 (commit `c17a3fa`), `search_ts` being
   unqueried was already in the gap register, and the §5 heading collision is fixed.
