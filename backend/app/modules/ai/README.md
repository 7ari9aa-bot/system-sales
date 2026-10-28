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

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `ai` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
