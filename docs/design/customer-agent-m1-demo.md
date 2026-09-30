# Customer Agent M1 — Live Demonstration Runbook

The M1 slice (retrieval → rerank → decision → verify → tools → grounding →
photo delivery) is shipped and CI-green. What remains from the owner's
definition of done is demonstrating the three behaviors on a REAL WhatsApp
conversation with real catalog photos. This is the path.

## 0. What is being demonstrated

| Behavior | Where it lives |
|---|---|
| Replies like a store employee | shipped earlier (AgentRunner + prompts) |
| Sends product photos | `resolve_product_media` tool + `hooks.send_media` |
| Understands customer photos | `find_product_by_image` tool + the vision pipeline |

Non-product photos (payment receipts, damage shots) are REFUSED with a
handover reason — the demo should show that too.

## 1. Prerequisites

- Migration `b4c5d6e7f8a9` applied and `python scripts/provision.py` run
  (CI does both; locally `alembic upgrade head` after pulling).
- Vision provider keys in the environment or `backend/.env`:

```
AI_EMBEDDING_VISION_API_KEY=<DashScope intl key>
AI_RERANKER_API_KEY=<Jina key>
```

  The base URLs/models are already defaulted (see `.env.example`). Keys are
  platform-level env — no tenant secret wiring exists yet for the vision
  stack (§9 of the design).
- The tenant's agent must have BOTH tools enabled — an `agent_tools` row per
  tool (`find_product_by_image`, `resolve_product_media`), the same way the
  existing read tools are attached.

## 2. Index the catalog (once per catalog, re-run after edits)

```
python scripts/index_product_images.py <tenant_id>
```

- Embeds every image of SELLABLE products only (draft/archived never reach
  retrieval).
- Idempotent: re-running updates the same rows (UNIQUE on
  image+model+version); safe after catalog edits.
- A changed embedding model means a full re-index by construction.
- VERIFY: `SELECT count(*) FROM product_embeddings WHERE tenant_id = ...;`
  should equal the number of gallery images on sellable products.

## 3. The conversation

1. Customer sends a PHOTO of a product (+ optional caption as the hint).
   Expected: the agent answers like a store employee about THAT product.
   Internally the current turn carried the photo as a real content part, the
   pipeline returned HIGH/MEDIUM/LOW, and the reply's numerals all trace to
   tool facts (grounding).
2. Customer: "وريني صورته". Expected: the text reply FIRST, then the gallery
   photos as separate image messages, each with its own `message.outbound`
   outbox event. Cap: four photos per reply.
3. Customer asks again. Expected: NO photo is re-sent — `sent_media` in
   `conversation_agent_states` holds every delivered image id and the
   no-resend rule skips them.
4. Customer sends a payment receipt. Expected: refusal + handover
   (`payment_proof_requires_human`) — never a confirmation of payment from
   an image.

## 4. What to watch

- `agent_runs.output` carries `media` and `shown_product_ids` per run.
- `tool_calls` rows record the vision tool executions and their latency —
  the §19 image-tool budget is 8s; embedding+rerank ride ONE tool call, so
  breaches are visible per row.
- `AIHandover` rows: any LOW-confidence match is presented with uncertainty,
  not silence; classifier refusals hand over with the reason attached.

## 5. Honest caveats before the demo

- The decision thresholds in `vision/thresholds.py` are PLACEHOLDERS until
  calibrated on the labelled corpus (§12.2/§23.7). HIGH/MEDIUM/LOW in this
  demo are shape, not measured quality — do not read the rates as metrics.
- Jina `jina-reranker-m0` commercial terms are still unconfirmed (§23.5) —
  fine for the demo, resolve before production traffic.
- Rate-limit the demo: image spend per customer per day is a budget gate
  (§16), and the transport timeout is 15s per provider call.
