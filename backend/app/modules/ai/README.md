# ai

AI domain — agents, tools, prompts, model_configs, memories, knowledge, agent_runs, tool_calls, model_calls, ai_usage.

## Where things are

- `agents/`
- `approvals.py`
- `budget.py`
- `chat/`
- `core/`
- `evaluation.py`
- `gateway.py`
- `guardrails.py`
- `handover.py`
- `hooks.py`
- `knowledge.py`
- `models.py`
- `multimodal.py`
- `policies.py`
- `policy.py`
- `prompts.py`
- `providers.py`
- `readiness.py`
- `router.py`
- `routers/`
- `runtime.py`
- `schemas.py`
- `secret_backfill.py`
- `tools.py`
- `trace.py`
- `usage.py`
- `versions.py`

## HTTP

45 endpoints. Route prefixes: `/ai`. Registered in `app/main.py`.

## Tables

- `agent_deployments`
- `agent_runs`
- `agent_tools`
- `agent_versions`
- `agents`
- `ai_budget_policies`
- `ai_budget_reservations`
- `ai_chat_messages`
- `ai_chat_threads`
- `ai_evaluations`
- `ai_handovers`
- `ai_provider_policies`
- `ai_usage`
- `approval_requests`
- `conversation_agent_states`
- `incoming_stock`
- `knowledge_items`
- `memories`
- `model_calls`
- `model_configs`
- `product_attributes`
- `product_embeddings`
- `prompts`
- `support_playbooks`
- `tool_calls`

## Depends on

Other modules imported from here: `analytics`, `billing`, `catalog`, `conversations`, `customers`, `identity`, `inventory`, `notifications`, `orders`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Large files and how to split them safely

Measured, not guessed. Check these again before cutting, because code moves.

**`agents/customer/tools.py` (about 1,270 lines).** Three parts: tool implementations, the
`CUSTOMER_TOOL_SPECS` text shown to the model, and `register_customer_tools()`. The
implementations form four groups that never call each other:

| Group | Tools | Shared helpers they use |
|---|---|---|
| catalog | `_search_catalog`, `_get_product_details`, `_get_product_photos`, `_find_product_by_image`, `media_payload_for_ids` | `_availability_map`, `_unit_prices`, `_money`, `sellable_product_statuses` |
| orders | `_get_my_orders` | `_money`, `_parse_bound_id` |
| store | `_get_store_info`, `_search_knowledge` | none beyond `_StrictArgs` |
| support | `_find_support_playbook`, `_handover_to_human` and the Arabic folding helpers | `_parse_bound_id` |

Every group needs `_StrictArgs`, so that goes in a shared file. No test patches any tool by
name (tests call `_get_store_info` and `_search_catalog` directly), so moving them does not
silently disable a patch. Keep `tools.py` as the facade that re-exports every name: `ai/tools.py`
and eight other files import from it, and `register_customer_tools()` must still register all
nine tools (`search_catalog`, `get_product_details`, `get_product_photos`, `find_product_by_image`,
`get_store_info`, `search_knowledge`, `get_my_orders`, `find_support_playbook`,
`handover_to_human`). After any move, assert that exactly those nine specs register. The module
docstring still says "seven tools"; it is out of date.

**`runtime.py` (about 1,600 lines).** One class, `AgentRunner`, of about 1,400 lines. It cannot
be split by moving functions; it needs the same dependency measurement as `pos/service.py`.

**Two traps seen in this repo.**
1. `gateway.py` re-exports names from `budget.py`. Patching `gateway._month_spend` changes
   nothing `reserve_budget` reads, so a test patching the alias passes or fails for the wrong
   reason. Patch the module that holds the logic.
2. Measure dependencies by every spelling: `self.x`, `ClassName.x`, and bare names. Counting
   only `self.` once made a tightly coupled class look independent.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `ai` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
