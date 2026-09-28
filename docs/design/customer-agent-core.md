# Customer Agent Core — Engineering Design

Design for the Customer Agent layer defined by the approved v1.0 spec
("Customer Agent — Core Architecture"; section references below (`§n`) point at
it). Governing metric: **Confident-Wrong Rate ≈ 0**.

Status: **providers verified against live keys on 2026-09-29**; the two new
transports are landed with tests. Everything else in this document is the
build plan mapped onto primitives that already exist in `backend/app/modules/ai/`.

## 1. Verified provider facts

Live-key verification, 2026-09-29 (cold single calls from Cairo-region network):

| Role | Provider / model | Wire schema | Verified | Measured |
|---|---|---|---|---|
| Chat + vision LLM | `alibaba/qwen3.8-omni-flash` via Vercel AI Gateway | OpenAI `POST {base}/chat/completions` | text chat; image via `content[].image_url`; `reasoning` field present; Arabic OK | ~3.0s text, ~2.1s text+image |
| Multimodal embedding | `tongyi-embedding-vision-flash` via DashScope intl | **DashScope native** `POST {base}/services/embeddings/multimodal-embedding/multimodal-embedding` | text-only, image-only, image+text items — one vector per item | **dim = 768**; ~0.29–0.79s |
| Reranker | `jina-reranker-m0` | Jina `POST https://api.jina.ai/v1/rerank` | query and documents may each be text or image; scores in [0, 1] | ~0.6s / 4 docs |

Consequences that settle open decisions from the spec:

- **Vector width is pinned: 768** (spec §23.6 resolved). pgvector column is
  `vector(768)`. A model change means a full re-index — `model` +
  `model_version` are stored on every row (§12.6), and mixed-model vectors are
  structurally impossible (UNIQUE per media row + model).
- **Fallback costs zero new code**: `qwen3.8-omni-flash` also exists on
  DashScope's OpenAI-compatible endpoint, so the §18 "Qwen timeout" row is a
  `model_configs` fallback row pointing at
  `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
- **Prompt caching is measurable**: the gateway's `usage` exposes
  `cached_tokens` (and `reasoning_tokens`) — the §7.1 cache-hit ratio and the
  thinking budget are both observable per call, not guessed.
- **Open**: Jina API commercial terms for `jina-reranker-m0` (spec §23.5) —
  confirm with the provider before production traffic.

## 2. What the agent reuses (spec rule 12 — no reinvention)

| Agent need | Existing primitive |
|---|---|
| Inference loop, rounds, tool calls, retries | `ai/runtime.py` `AgentRunner` |
| Model resolution per tenant/alias | `ai/gateway.py` `resolve_model_config` (tenant `model_configs` row → settings fallback) |
| LLM transport | `ai/providers.py` `AIProvider` (OpenAI-compatible) — Qwen rides it unchanged |
| Cost control | §42 `estimate → reserve → call → settle` + `ai_monthly_budget_cap_default` |
| Behavior guardrails | `ai/guardrails.py` |
| Provider failure isolation | §47 circuit breaker, driven by `ExternalProviderError` |
| Change capture (§11.2) | outbox events → worker runtime |
| Tenancy | RLS + `app.tenant_id` GUC; every agent-owned table carries `tenant_id` (§20) |

## 3. New transports (landed)

`ai/providers.py` gains two thin transports, same discipline as the existing
ones (injectable `httpx.AsyncClient` for `MockTransport` tests, parsed errors
become `ExternalProviderError`):

- `MultimodalEmbeddingProvider.embed()` — DashScope native schema; items of
  `text`, `image`, or both in one vector; validates the response count and the
  expected dimension (768) so silent dim drift fails loudly.
- `RerankerProvider.rerank()` — Jina schema; `results` re-sorted by score
  descending with **caller-order indexes preserved**; scores outside [0, 1]
  raise (an out-of-range score would silently invalidate every decision
  threshold).

Transport timeout is 15s (the §19 image tool budget is 8s — the remainder is
pipeline work, not transport).

Config keys (`core/config.py`, mirrored in `.env.example`):
`ai_embedding_vision_{base_url,api_key,model,dimensions}` (defaults pin
`tongyi-embedding-vision-flash` / 768 / DashScope intl) and
`ai_reranker_{base_url,api_key,model}` (defaults pin `jina-reranker-m0`).

Later, both resolve through the gateway like the chat model: aliases
`vision_embedding` and `vision_rerank` with per-tenant `model_configs` rows
taking precedence over the settings defaults.

## 4. Package layout (spec §22) — slice status

```
backend/app/modules/ai/
├── providers.py          # + MultimodalEmbeddingProvider, RerankerProvider  [LANDED]
└── agents/customer/
    ├── vision/
    │   ├── providers.py  # (transport lives in ai/providers.py)           [DONE]
    │   ├── indexer.py    # offline embedding of approved product media    [M1]
    │   ├── retrieval.py  # pgvector top-30 → product groups → ~10        [M1]
    │   ├── reranker.py   # image-vs-image rerank over candidates         [M1]
    │   ├── decision.py   # confidence from the four factors              [M1]
    │   ├── thresholds.py # calibrated ONLY on the real image corpus      [M1]
    │   └── verifier.py   # DB verification (active, variants, stock)     [M1]
    ├── turn.py / intake.py / referents.py / state.py / capabilities.py    [M2]
    ├── ledger.py / grounding.py / media.py / response.py / handoff.py     [M2]
    ├── feeder.py / prompt.py / tools.py                                   [M3]
    └── evaluation/                                                        [M4]
```

## 5. Data model (spec §20)

```sql
CREATE TABLE product_embeddings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    product_media_id UUID NOT NULL REFERENCES product_media(id) ON DELETE CASCADE,
    vector        vector(768) NOT NULL,
    model         TEXT NOT NULL,          -- 'tongyi-embedding-vision-flash'
    model_version TEXT NOT NULL,
    content_kind  TEXT NOT NULL,          -- 'image' | 'text' | 'image+text'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_media_id, model, model_version)
);
CREATE INDEX ON product_embeddings USING hnsw (vector vector_cosine_ops);
-- RLS: tenant_isolation, same as every tenant-scoped table.
```

`product_attributes`, `agent_turns`, `conversation_agent_state`,
`knowledge_snapshots`, `conversation_seen_versions`, and the image-eval tables
follow the spec §20 ownership split (agent-owned vs read-only) and the same
RLS pattern. Media identity is `media_asset_id`/`product_media_id` — never a
provider URL.

## 6. Vision pipeline mapping (spec §12)

```text
customer photo (+ hints)            [deterministic pre-filter]
  → MultimodalEmbeddingProvider     image (+caption text when present)
  → pgvector cosine top-30          → group by product → ~10 candidates
  → RerankerProvider                customer image vs candidate product images
  → decision.py                     HIGH / MEDIUM / LOW from:
                                      (1) top-1 absolute score
                                      (2) top-1 − top-2 gap
                                      (3) embedding ↔ reranker order agreement
                                      (4) attribute consistency vs hints
  → verifier.py                     live DB: active? variants? stock? as_of
  → Fact Ledger                     source_tool=find_product_by_image
```

Non-negotiables carried over: a missing/failed reranker means **never HIGH**
(§12.2); thresholds live in `thresholds.py` and are calibrated on the real
image corpus (200–500 labelled photos, including out-of-catalog images that
must yield "not found"), never guessed.

## 7. Cost/latency plan anchored on measurements (spec §7.1, §16)

- Static Store-Brief prefix first, dynamic parts last — then `cached_tokens`
  from the gateway usage becomes the cache-efficiency metric per turn.
- `reasoning_tokens` is reported: per-turn thinking budgets (greeting = 0,
  comparison/ambiguity = more) are enforced via `max_tokens` and round limits,
  and observed in usage.
- Both embedding and rerank run inside ONE tool call (`find_product_by_image`);
  no extra Qwen round-trips between them (§19).
- Image spend per customer per day is a budget-gate counter (§16 Cost row).

## 8. Build order

1. **M0 — transports (landed):** the two providers, config keys, wire tests.
2. **M1 — vision vertical slice:** `indexer` (offline), `retrieval` +
   `reranker` + `decision` + `verifier`, thresholds calibrated on the first
   tranche of the labelled corpus; acceptance = the corpus metrics table of
   spec §21 (top-1/top-3 with and without reranker, out-of-catalog honesty).
3. **M2 — agent core on AgentRunner:** turn coordinator (deadline/budgets),
   intake + normalization, referent resolver, state engine + validator, Fact
   Ledger, grounding controller, response planner, capability resolver.
4. **M3 — knowledge layer:** Knowledge Compiler, snapshots, change capture
   consumer, Context Feeder (cards + deltas + cached prefix).
5. **M4 — hardening:** handoff states, replay harness + eval suite (gates
   every prompt/model/threshold change), observability spans per spec §21.

## 9. Security notes

- Keys are platform-level env for now; per-tenant overrides go through
  `model_configs` + the §68 envelope secret store when multi-tenancy of the
  vision stack demands it.
- Customer media leaves tenant storage only as provider-fetchable https/data
  URLs minted outside the agent (Response Resolver); the adapters accept no
  tenant credentials, and nothing customer-controlled is ever interpolated
  into system context (§7 untrusted zone).
- The agent never speaks to DashScope/Jina directly — tools go through the
  Tool Gateway's tenant/customer/conversation binding (§11).
