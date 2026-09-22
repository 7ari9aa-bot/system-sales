# Wave 0 — Live Correctness Bugs (5 parallel fixes)

> Parent: `2026-09-22-full-system-completion.md`. Each fix is one subagent, disjoint files. Agents never run git; DB-backed tests verified by orchestrator in CI (agents run `ruff` + `pytest --collect-only`).

**Verified evidence (2026-09-22):** all five defects confirmed in the working tree.

---

### Task W0.1 — AI auto-reply RAG retrieval function

**Files:**
- Modify: `backend/app/modules/ai/knowledge.py` (add function; existing API: `ingest_knowledge`, `search_knowledge:67`, `add_memory`, `search_memory`)
- Modify: `backend/app/modules/ai/hooks.py:118-127` (import site) — also fix `hooks.py:221` `aggregate_version=1` → use the conversation/message real version if available, else keep and justify in code comment
- Test: `backend/tests/test_ai_hooks_rag.py` (new)

**Defect:** `hooks.py:119` does `from app.modules.ai.knowledge import retrieve_relevant` — the name does not exist. The `except Exception` at hooks.py:130 swallows the ImportError, so every auto-reply silently runs with `knowledge_context=None`.

**Fix:** implement in `knowledge.py`:

```python
async def retrieve_relevant(
    session, tenant_id, *, query: str, customer_id=None, limit: int = 5
) -> list[str]:
    """Auto-reply retrieval: wraps search_knowledge, enforces §157
    customer_facing visibility, returns plain-text snippets."""
```

**Test (fails before, passes after):** monkeypatch `app.modules.ai.knowledge.retrieve_relevant`-backed retrieval (or `search_knowledge`) to return snippets; drive the auto-reply hook; assert the model call received the knowledge context block. Before fix: context is always None (import fails silently) → FAIL. After: context present → PASS. Add a second test: retrieval raising → reply still proceeds, warning logged.

### Task W0.2 — Orders Undo cancel path

**Files:**
- Modify: `frontend/src/app/(dash)/orders/page.tsx:145-165`
- Read first: `frontend/src/lib/api.ts` (apiClient wrapper), `frontend/src/lib/queries.ts` (existing order mutations), `backend/app/modules/orders/router.py` (real cancel route + expected payload)

**Defect:** undo does raw `fetch('/api/orders/${order.number}/cancel')` — wrong origin (bypasses the Vercel rewrite/apiClient base), uses `number` where the API keys by `id`, ignores non-2xx.

**Fix:** use the project's apiClient/mutation pattern with `order.id` and the real route from `orders/router.py`; on success invalidate the orders list query; keep success/danger toasts.

**Verify:** `npm run lint` + `npx tsc --noEmit` green in `frontend/`. If an orders e2e/unit spec exists, extend it; otherwise note for orchestrator.

### Task W0.3 — notifications/digest.py import-safety

**Files:**
- Modify: `backend/app/modules/notifications/digest.py`
- Read first: `backend/app/modules/platform/models.py` (~line 205-264: canonical `NotificationPreference`)
- Test: `backend/tests/test_notifications_digest_import.py` (new)

**Defect:** `digest.py` re-declares `__tablename__ = "notification_preferences"` — importing the module would raise SQLAlchemy mapper/table redefinition. Module is currently dead (never imported), so the crash is latent.

**Fix:** delete the local `NotificationPreference` class; import the canonical one from `platform.models`. Keep `NotificationDigest`/`NotificationAggregator` (wired in Wave 4, §166). No behavior change beyond import-safety.

**Test (fails before):** `import app.modules.notifications.digest` succeeds and `digest.NotificationPreference is platform_models.NotificationPreference`. Before fix: import raises (table redefinition) → FAIL.

### Task W0.4 — Channel-account lifecycle enforcement

**Files:**
- Modify: `backend/app/modules/customers/router.py:376-417` (channel-account upsert)
- Read first: `backend/app/modules/platform/models.py:119-168` (`ChannelAccount` states + `validate_transition`)
- Test: extend existing channel-account tests or create `backend/tests/test_channel_account_lifecycle.py`

**Defect:** §145 7-state lifecycle + transition table exist but `validate_transition` is dead code; upsert writes `status` directly → any illegal jump is accepted.

**Fix:** on upsert/update, when `status` changes on an existing row, call `validate_transition` and reject illegal transitions with the project's `ValidationError`; initial creation keeps its defined entry state. Do not break the webhook-credential upsert path (idempotent re-register must not fail).

**Test (fails before):** illegal transition (e.g. `active` → a state the table forbids) returns 4xx; legal transition and idempotent re-upsert succeed. Before fix: illegal accepted → FAIL.

### Task W0.5 — Real aggregate_version on domain events (§153)

**Files:**
- Modify call sites: `backend/app/modules/orders/service.py:338,503,818`, `customers/service.py:832`, `privacy/service.py:140`, `ai/evaluation.py:115,223`, `conversations/gateway/ingest.py:199` (⚠ ingest.py has UNCOMMITTED in-flight changes — minimal additive diff only, never revert)
- Read first: `backend/app/core/events/writer.py:56-81`, `core/model_kit.py` (VersionMixin)
- Test: `backend/tests/test_event_aggregate_version.py` (new)

**Defect:** every call site passes literal `1/2/3`; consumers cannot order events per aggregate (§153).

**Fix:** when the aggregate model carries `VersionMixin`, pass the row's real `version` (post-mutation) instead of literals; keep explicit values only where the aggregate has no version column, with a one-line justification comment. No envelope shape change (that's Wave 2).

**Test (fails before):** create → mutate → mutate an order; assert the three order events carry the aggregate's real increasing versions matching the row history. Before fix: literal 1/2/3 regardless of actual version → FAIL.

---

## Global constraints (all tasks)
- No git commands. Minimal additive diffs; never revert pre-existing uncommitted changes.
- Follow existing patterns (service-layer mutations, outbox `add_outbox_event`, error types from `core/errors.py`).
- `cd backend && ruff check app tests` must be clean; `python -m pytest tests/<new_test> --collect-only -q` must collect (DB fixtures skip locally without DATABASE_URL_APP_ADMIN — expected).
- Report: files changed, fail-before evidence, checks run + results, what needs orchestrator DB/CI verification.
