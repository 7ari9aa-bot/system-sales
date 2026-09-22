# CONTRACT AUDIT — "defined, then bypassed"

Scope: `backend/app/**` (contracts live in the shared layer, `app/core/**`).
Method: read `app/core/**` for candidate contracts → grep real non-test callers in
`app/` → read the bypassing call site and state what is lost → rank by blast radius
(a bypassed contract that a **stored row** or an **external consumer** depends on is
worst, because the data is already wrong on disk).

Executable companion: `backend/tests/test_contract_reachability.py`
(`ENVIRONMENT=local ./.venv/Scripts/python.exe -m pytest tests/test_contract_reachability.py -q`
→ 23 passed, 1 xfailed).

## The precedent (verified, not assumed)

`app/core/events/schemas.py:188 deserialize()` requires `occurred_at` /
`aggregate_type` / `aggregate_id`; `app/core/events/writer.py:54-70` now builds a real
envelope with `build_envelope()` + `serialize()`. **Already fixed today** — the
published row carries every routing key. It is reproduced here only as the template
for the class. What it teaches: *the half nobody called was a contract, so consumers
relied on it, and an isolated unit test on it proved nothing.*

## Reachability summary

| Pair | write half (callers) | read half (callers in `app/`) | round-trips? |
|---|---|---|---|
| §19 envelope | `schemas.serialize` — `writer.py:70` | `schemas.deserialize` — **NONE** | ✅ JSON-native values / ❌ `Decimal`, `datetime` |
| outbox row → bus → consumer | `writer.add_outbox_event` | 5 hand-parsers, no `deserialize` | ✅ (by hand) |
| retry row | `writer.add_outbox_event` | `workers/base._republish_after` hand-inserts | ⚠️ guarantee not enforced |
| idempotency replay record | `IdempotencyService.complete` | `IdempotencyMiddleware._send_stored` | ✅ (test added) |
| billing period snapshot | `BillingSnapshotService.snapshot_lines` | `…snapshot_view` (router only) | ✅ (test added) |
| cursor | `pagination.encode_cursor` | `pagination.decode_cursor` | ✅ |
| ETag / If-Match | `idempotency.etag_for` | `idempotency.parse_if_match` | ✅ |
| visitor token | `security.create_visitor_token` | `security.decode_visitor_token` | ✅ |
| unified error body | `errors.build_error_body` | **no inverse** — 4 hand-built variants | ❌ 3 shapes |
| metric definitions | `metrics.MetricSpec.as_dict` | no inverse (row columns) | ✅ (test added) |

---

## Finding 1 — §19 envelope: the pair is not type-preserving, and a real producer passes a `Decimal`  **HIGH**

**Contract.** `schemas.serialize()` / `schemas.deserialize()`; `writer.py:9-12` states
the contract explicitly: *"what the relay publishes is exactly what
`schemas.deserialize()` rebuilds."*

**Real producer.** `app/modules/orders/service.py:305-321` publishes `order.created`
with `"grand_total": order.grand_total` — a `Decimal` (the column is `MONEY`).

**What actually happens.** `serialize` → `envelope.model_dump(mode="json")` →
`json.dumps(..., default=str)`, so `Decimal("76.50")` becomes the **string** `"76.50"`.
`deserialize` has no inverse coercion, so it rebuilds a payload whose value is a string.
`deserialize(serialize(x)) != x`.

**Evidence (executed, `--runxfail` shows the assertion genuinely fails):**
`before={'grand_total': Decimal('76.50')} after={'grand_total': '76.50'}`.

**Blast radius — stored row + external consumer, i.e. the worst case.**
- The row is on disk: `outbox_events.payload` (JSONB), written by `writer.py:75`.
- It is published to Redis and read by the SSE gateway
  (`app/modules/realtime/router.py:315-327`) — a **browser client** — and by
  `webhook.deliver`, an **external subscriber**.
- It is copied into `event_log` (§152 durable replay, `outbox.py:220`).

**The codebase already knows this is wrong in one place and not the other.**
`orders/service.py:733` (`order.refunded`) explicitly casts: `float(refund_amount)`.
`order.created` does not. `privacy.customer_deleted` (`privacy/service.py:107`) passes
an all-JSON-native report, so `orders` is the only live offending site.

**Fix routing (not mine — `app/` is owned by other agents).** Either make the pair
type-preserving, or normalise the producer (a string or `float`, matching
`order.refunded`). The test is `xfail(strict=True)`: the moment it is fixed the test
**XPASSes and CI goes RED** until the marker is removed, so the decision cannot be
forgotten. If the team decides stringification IS the contract, delete the marker and
update `writer.py`'s docstring — do not leave it silently contradicting.

## Finding 2 — the §19 envelope's READ half is bypassed by every real consumer  **HIGH**

`deserialize()` has **zero non-test callers** in `app/`. Five consumers hand-parse the
same envelope instead, each re-deriving the field names:

- `app/modules/realtime/router.py:315-327` — `json.loads(meta)`, reads `meta["tenant_id"]`, fails CLOSED on absence.
- `app/workers/message_worker.py:87` and `app/workers/platform_workers.py:34,65` — `event.meta.get("tenant_id")`.
- `app/workers/base.py:187` — `event.meta.get("outbox_id")` (the dedupe key).
- `app/core/events/outbox.py:177-223 _write_event_log` — hand-maps envelope fields into `event_log` columns; notably `occurred_at = row["created_at"]` (the outbox row's DB timestamp) rather than `meta["occurred_at"]` (the envelope's own instant), so the §152 replay history does not record the envelope's timestamp.
- `app/workers/inspector.py:48-65 list_dlq` — hand-parses `payload` / `meta`.

**What is lost.** The envelope is only a *convention* on the read side: any of these
five can drift from `schemas.py` with no test failing. Finding 1 is exactly that drift
already happening on the value-type axis.

**Blast radius.** The consumers are the workers, the SSE client and the DLQ tooling —
so a drift is silent and platform-wide. Not "wrong data today" (the keys are present
since the writer fix), but the contract is unenforced where it matters.

**Fix routing.** Out of scope for this audit (`app/` owned elsewhere). Recommended:
have at least the SSE gateway and the relay's `_write_event_log` call `deserialize()`
so the contract is exercised on the read path; then this file's round-trip test is the
regression guard.

## Finding 3 — the retry path bypasses the canonical outbox writer  **MEDIUM (latent)**

**Contract.** `writer.py:1` — *"Outbox writer — the ONLY way domain code stages
events."* It is what guarantees every outbox row's `meta` is a deserializable §19
envelope.

**Bypass.** `app/workers/base.py:237-269 _republish_after` hand-inserts the retry row:
`pg_insert(OutboxEvent).values(payload=event.payload, meta=meta, …)`. No
`build_envelope`, no `serialize`, no validation. It is the **only** other
`OutboxEvent` insert in `app/`.

**What is lost / additional defects found on the path.**
- The envelope guarantee is simply not enforced here; the path works today only because `meta` was copied from an envelope-bearing event.
- `aggregate_id` silently becomes a random `uuid.uuid4()` (line 258-260) when `meta["aggregate_id"]` is absent, so a retry row can point at a fabricated aggregate.
- `.on_conflict_do_nothing()` has **no `index_elements`**, and `outbox_events` has **no unique constraint** (`platform/models.py:66` is a plain index) — so the clause is a no-op.
- `meta["outbox_id"]` is copied from the original row, not refreshed to the new row id. That is *deliberate* (it is the consumer-inbox dedupe key, `workers/base.py:187`), but it is undeclared, and it means the writer's invariant `meta["outbox_id"] == str(row.id)` (`writer.py:85`) does **not** hold for retry rows. Recorded so nobody "fixes" it into a double-send.

**Blast radius.** `outbox_events` rows on disk + whatever the relay publishes from them.
Latent, not currently wrong.

## Finding 4 — the unified error contract is defined once and bypassed by four writers, in three shapes  **HIGH**

**Contract.** `app/core/errors.py:114 build_error_body()` →
`{"error": {code, message, retryable, request_id}}`. Used by `app/main.py:108-113` for
`DomainError`.

**Bypasses.**
| site | shape | note |
|---|---|---|
| `core/middleware.py:235-257 _emit_error` | `{"error": {…}}` hand-built | docstring claims it *"uses the unified contract"*; hardcodes `retryable: False`, `request_id: None` |
| `core/idempotency.py:451-477 _emit_error` | `{"error": {…}}` hand-built | third copy (this one gets `retryable`/`request_id` right) |
| `core/middleware.py:206` | `{"detail": "try again later"}` | 429, auth bucket, Redis down |
| `core/middleware.py:211-219` | `{"detail", "tier", "retry_after"}` | 429 — **different shape**: no `code`, no `retryable`, no `request_id` |
| `main.py:117` | `{"detail": str(exc)}` | 403 `PermissionError` |
| `core/errors.py:51 DomainError.to_dict()` | `{"code", "message", "details"}` | **DEAD** — zero `app/` callers, only tests; docstring calls it *"serializable form for API error responses"*, which is false |

**Consumer.** `frontend/src/lib/api.ts:85` and `frontend/src/lib/auth-api.ts:37` read
`body?.error?.message ?? body?.detail`. So a rate-limited response degrades to the bare
string and loses `code` / `retryable` / `request_id` — and `retryable` is what drives the
retry UX in `frontend/src/app/auth/login/page.tsx` and `signup/page.tsx`.

**Blast radius.** Every 429 / 413 / 403 response, plus a dead fifth variant that invites
a future caller to emit a fourth shape.

**Fix routing.** `app/core/middleware.py`, `app/core/idempotency.py`, `app/main.py`,
`app/core/errors.py` are all outside my file scope. Recommended: one ASGI-level helper
that calls `build_error_body` (constructing a `DomainError`), and delete or wire
`DomainError.to_dict()`.

## Finding 5 — a second session dependency that skips RLS binding, and other dead contracts  **LOW–MEDIUM**

| contract | callers in `app/` | risk |
|---|---|---|
| `core/db.py:103 get_session` | **0** | A duplicate of `identity/deps.py:83 get_db` (`DbSession`) that does **not** call `bind_tenant`. Adopting it silently drops the tenant GUC — the exact failure golden rule 4 exists to prevent. A landmine, not a live bug. |
| `automation/service.py:104 WorkflowService.execute_for_event` | **0** | The `Workflow.trigger_event` column and the ACTIVE-workflow dispatch exist, but nothing routes a bus event into them, so an "active" workflow never fires. Feature absent; no wrong data. |
| `ai/knowledge.py add_memory`, `search_memory` | **3** (was 0) | Wired: `ai/runtime.py` writes an `agent_inferred` summary on run finalization and recalls customer memories into context; `ai/router.py` `/ai/memories*` staff-entered creation + review surface (§158). `privacy/service.py` DELETE-from-`memories` step is now real erasure of live data. |
| `ai/gateway.py:143 expire_stale_reservations` | **0** | `RECURRING_JOBS` (`scheduler_worker.py:42-56`) sweeps inventory reservations but not `AIBudgetReservation`, so a crashed run's row stays `active` forever. Bounded: `_reserved_spend` (`gateway.py:127-140`) already filters `expires_at > now()`, so the cap is not actually held — the row is just never cleaned. |
| `core/circuit_breaker.py:208-218 breaker_states/open_breakers/reset_breakers` | **0** (diagnostics) | `platform/router.py` health does not surface breaker state. Diagnostics gap only. |

These are the repo's known failure mode ("complete, unit-tested, imported by nothing"),
not bypassed contracts. `tests/test_no_dead_core_modules.py` covers them at *module*
granularity; it cannot see a dead function inside a live module, which is why they
survive. Listed so the orchestrator can triage them deliberately.

---

## Deliberate divergences — do NOT "fix" these

1. **The writer injects `event_type` into the payload.** `writer.py:75` stores
   `{"event_type": event_type, **payload}` because the workers route on
   `payload["event_type"]` (`message_worker.py:86`, `platform_workers.py:32,63`). So the
   rebuilt envelope's payload is the caller's payload **plus one key**. The test asserts
   exactly that shape rather than full equality.
2. **The row's `meta` is `serialize()`'s output PLUS `outbox_id`.** `writer.py:85` mutates
   `event.meta` *after* serialization so the consumer-inbox dedupe key is stable across
   relay crash-reclaim republishes. Still deserializable (it lands in `envelope.meta`),
   but the writer's docstring line 69 ("the row IS what `deserialize()` reads") is
   imprecise.
3. **`meta["outbox_id"] != str(row.id)` on retry rows** — see Finding 3.

## What this audit did NOT do

- **No `app/` change.** Every fix above belongs to a file another agent owns right now.
- **No live-Postgres verification.** There is no local Postgres, so the JSONB hop in the
  billing-snapshot test is emulated with `json.dumps`/`json.loads` (the exact
  encode/decode the column performs) rather than exercised against a real column.
- **Findings 1, 2 and 4 are greps plus executed round-trip probes**, not end-to-end runs
  of the SSE gateway or a webhook subscriber. The producer-side evidence for Finding 1
  is executed (`--runxfail` → FAILED); the consumer-side consequence (a browser seeing
  `"76.50"`) is read from the code, not observed on a live stream.
