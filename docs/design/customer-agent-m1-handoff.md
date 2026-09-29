# Customer Agent M1 — Handoff (continue here)

Contract for the NEXT session. Read this first, then
`docs/design/customer-agent-core.md` (the engineering design) and the approved
v1.0 Customer Agent spec. Goal (owner, 2026-09-29): the agent replies to
customers on WhatsApp/Messenger/Instagram **like a store employee**, **sends
product photos** when asked, and **understands customer photos**.

## 1. What is DONE, pushed, and CI-green (do not redo)

- `a30ae3e` CI gates fixed (diagnostics ImportError was also re-merging the
  11-module SCC; head pins moved to the then-head; /tasks specs retired).
- `a9a8297` vision transports: `MultimodalEmbeddingProvider` +
  `RerankerProvider` in `app/modules/ai/providers.py` (15s vision timeout,
  dim validation, score-range guard) + config keys + 8 wire tests.
- `6d317fb` `provision._write_app_password` derives DSNs from the provisioned
  DB (was hardcoding the production Supabase pooler into every .env).
- `3faf3cd` ToolCall insert race → savepoint + winner's outcome; hooks
  docstring now matches the fail-loudly policy.
- `6f7430d` data layer: `ProductEmbedding` / `ProductAttribute` /
  `ConversationAgentState` in `app/modules/ai/models.py`; migration
  `a1b2c3d4e5f6_customer_agent_vision_tables.py` (Vector(768) + HNSW cosine,
  tenant_isolation RLS, guarded sales_app grants — APPLIED locally, provision
  re-run, 3 policies verified); `vision/schemas.py` (ImageKind, Confidence,
  Candidate, MatchResult), `vision/thresholds.py` (VisionThresholds —
  PLACEHOLDER values pending corpus calibration), `vision/classifier.py`
  (only PRODUCT runs the pipeline; payment_proof/complaint → handoff);
  gate pins in `tests/test_tenancy_and_fts_schema_debt.py` → `a1b2c3d4e5f6`.

## 2. Verified provider facts (live keys, 2026-09-29)

```
alibaba/qwen3.8-omni-flash  (Vercel AI Gateway, OpenAI schema): chat + image
  parts OK; usage.cached_tokens / reasoning_tokens observable.
tongyi-embedding-vision-flash (DashScope intl, NATIVE schema, dim=768):
  text-only / image-only / image+text items, one vector per item.
jina-reranker-m0 (https://api.jina.ai/v1/rerank): query and documents may be
  text or image; scores in [0,1].
OPEN: confirm Jina m0 commercial API terms (spec §23.5).
```

## 3. Build order for M1 (each step lands with tests)

1. `vision/retrieval.py` — embed the customer image (+text hint) via
   `MultimodalEmbeddingProvider`, then pgvector cosine top-30
   (`product_embeddings` JOIN `product_images` JOIN `products`), group per
   product (DISTINCT ON product_id), cap ~10 → `Candidate` list.
   **CONSTRAINT: parameter-bound `sa.text()` SQL only, tenant_id bound — NO
   new cross-module import sites (the boundary ratchet sits at 99).**
2. `vision/reranker.py` — `RerankerProvider.rerank(query=<customer image
   data-url>, documents=[{"image": candidate.image_url}])`; map result
   indexes back to candidates (provider returns caller-order indexes).
3. `vision/decision.py` — HIGH iff top-1 ≥ `high_floor` AND gap ≥ `gap_min`
   AND the winner is in the embedding top-`agreement_top_n`; MEDIUM when
   top-2 within `medium_band`; LOW below `rerank_floor`.
   **A failed/absent reranker ⇒ NEVER HIGH (spec §12.2).**
4. `vision/verifier.py` — product sellable (read `SELLABLE_PRODUCT_STATUSES`
   the same way `tools.py::_order_deps` does) + active variants with
   available stock (`on_hand - reserved`); returns business dict only.
5. `vision/pipeline.py` — orchestrate 1→4 into `MatchResult`
   (confidence, candidates[{product_id,title,verified,available_variants}],
   reason, as_of). **No URLs, no scores in the model-visible result.**
6. `vision/indexer.py` + `scripts/index_product_images.py` — embed approved
   `product_images` (batch items), idempotent upsert
   (`uq_product_embeddings_image_model_version`), skip non-sellable products.
7. Tools in `app/modules/ai/tools.py`:
   - `find_product_by_image` (LOW, read-only): args {image_kind, hints};
     `classifier.classify` gates (non-product → DomainError naming the
     handoff reason); customer image comes from RUNNER-INJECTED context
     (`context["customer_image"]` = signed URL), never from model args;
     no image in turn → DomainError.
   - `resolve_product_media` (LOW): args {product_id, selection∈primary|all};
     returns `[{image_id, alt, position}]` — **image_ids only, NO URLs**.
8. Runner (`app/modules/ai/runtime.py`):
   - last inbound image attachment → `ObjectStorage.signed_url(storage_key)`
     → context + the CURRENT user turn becomes multimodal content parts
     (text + image_url) so Qwen sees the photo (verified working);
     history images stay text markers (spec §7.1.3).
   - after the loop: collect media from `resolve_product_media` ToolCall
     rows (ids → urls server-side, cap 4) into `AgentRunResult.media`
     [{image_id, image_url, alt}]; collect shown product_ids into
     `shown_product_ids`.
   - grounding v1 (`agents/customer/ledger.py` + `grounding.py`): facts ONLY
     from tool results (+ tool args for create_order quantities); extract
     numerals (fold Arabic-Indic ٠-٩); every numeral must substring-match a
     fact value; fail → ONE regeneration (no tools, corrective instruction);
     fail again → content=None + guardrail_reason="grounding_failed" (the
     existing hook path turns that into AIHandover). Skip when no tool
     results (the unsourced_claim gate owns that case).
9. Hooks (`app/modules/ai/hooks.py`): after the text reply, send
   `result.media` via `ConversationService.add_message(media_url=...,
   media_type="image")`, ONE `message.outbound` outbox event per media
   message, and append sent_media to `conversation_agent_states`
   (upsert on conversation_id, bump state_version). No image re-sent while
   it is in sent_media (spec §13).
10. Tests: decision matrix (incl. reranker-down ⇒ never HIGH), classifier
    gating, reranker index mapping, indexer idempotency, tool gating
    (payment_proof refused), grounding (Arabic-Indic digits, regenerate-once,
    handover-after-twice), no-URL-in-model-result assertion. Full suite +
    CI green before merge.

## 4. Environment (this machine)

- Docker Desktop at `C:\Users\CS\AppData\Local\Programs\DockerDesktop\Docker
  Desktop.exe`; containers `infra-postgres-1` / `infra-redis-1` (compose:
  `docker compose -f infra/docker-compose.yml up -d postgres redis`).
- Test env (export before pytest): `ENVIRONMENT=local`,
  `DATABASE_URL_ADMIN=postgresql+asyncpg://postgres:postgres@localhost:5432/sales`,
  `SALES_APP_DB_PASSWORD=ci-app-password`,
  `DATABASE_URL_APP=postgresql+asyncpg://sales_app:ci-app-password@localhost:5432/sales`,
  same for `DATABASE_URL_APP_ADMIN` / `DATABASE_URL`.
- Full suite ≈ 40 min on Windows; `tests/perf/test_hot_path_budgets.py`
  fails locally only (p95 vs budget) — CI-green, do not chase.
- After touching models/migrations: `alembic upgrade head` + `python
  scripts/provision.py` (the policy gate test needs the new policies).

## 5. Warnings for the next session

- This session's tool channel degraded near the end: fabricated file-write
  confirmations and fake command outputs appeared. **Verify every Write with
  a tiny read/parse; prefer small commands; never trust a large pasted
  output without an independent check.** Three garbage files
  (`retrieval.py`, `reranker.py`, `decision.py`) were created by that noise
  and DELETED — if they reappear, delete them again.
- ALL API tokens shared in chat (GitHub full-admin, Vercel ×2, Supabase,
  DashScope, Jina) must be ROTATED — they live in the session log.

## 6. Acceptance (the owner's goal, verbatim)

Text replies like a store employee = SHIPPED. Sending product photos and
understanding customer photos = this handoff's steps 1-9. Done means: full
suite + CI green AND the three behaviors demonstrable end-to-end on a real
WhatsApp conversation with real catalog photos.
