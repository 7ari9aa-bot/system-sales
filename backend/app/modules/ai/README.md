# ai

AI domain — agents, tools, prompts, model_configs, memories, knowledge, agent_runs, tool_calls, model_calls, ai_usage.

## Where things are

- `agents/`
- `approvals.py`
- `budget.py`
- `chat/`
- `constants.py`
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

**`agents/customer/tools/` (done 2026-10-28; it was one 1,270-line `tools.py`).** A package now:

| File | What it holds |
|---|---|
| `catalog.py` | `search_catalog`, `get_product_details`, `get_product_photos`, `find_product_by_image`, stock and price lookups |
| `orders.py` | `get_my_orders` (by invoice number) |
| `store.py` | `get_store_info`, `search_knowledge` |
| `support.py` | `find_support_playbook`, `handover_to_human`, the Arabic folding helpers |
| `_shared.py` | `_StrictArgs`, `_money`, `_parse_bound_id`, `sellable_product_statuses` |
| `specs.py` | `CUSTOMER_TOOL_SPECS` (the text the model sees) and `register_customer_tools()` |
| `__init__.py` | Re-exports every name the old file had, so `from ...customer.tools import X` still works |

To add a tool: write its handler and args in the matching group file, add its `ToolSpec` to
`specs.py`, and re-export any name other code imports from `__init__.py`. The groups never call
each other; they only share `_shared.py`. Order inside a file matters: `support.py` builds
module-level constants from `_fold_arabic`, so that function must stay above them.

How the split was proved: every one of the 38 definitions was compared as a syntax tree against
the old file (none missing, none changed), the nine tools still register, and deleting one spec
makes `test_language_only_tools_are_registered` fail. The module docstring in `__init__.py`
now lists all nine tools.

**`runtime.py` (about 1,600 lines).** One class, `AgentRunner`, of about 1,400 lines. It cannot
be split by moving functions; it needs the same dependency measurement as `pos/service.py`.

**Two traps seen in this repo.**
1. `gateway.py` re-exports names from `budget.py`. Patching `gateway._month_spend` changes
   nothing `reserve_budget` reads, so a test patching the alias passes or fails for the wrong
   reason. Patch the module that holds the logic.
2. Measure dependencies by every spelling: `self.x`, `ClassName.x`, and bare names. Counting
   only `self.` once made a tightly coupled class look independent.

## Platform invariants

- `register_tool()` is fail-closed: a DIFFERENT `ToolSpec` under an existing
  tool name must pass `allow_override=True`; re-registering the same spec is
  idempotent. A tool name is a platform contract, not a slot two agents may
  silently fight over.
- Canary rollout buckets conversation-less runs (job/API agents) by the
  inbound event id when the caller carries one, otherwise by the agent id, so
  a retry of the same work sees the same version.
- `AgentRunResult.model` is the gateway alias; `AgentRunResult.model_name`
  (and `agent_runs.output.model_name`) is the concrete model the provider
  says answered. Do not collapse the two.
- `ALIASES` lives in `gateway.py` ONLY. `runtime.py` imports it; there is no
  second copy (an identity test pins this). Adding a model alias means editing
  `gateway.py` and nothing else — a definition validated against the gateway
  set must resolve identically at run time, never silently fall back to
  `"fast"`.
- Per-kind hooks (`pre_run_hook` / `post_run_hook` / `context_builder`) are
  declared on `AgentDefinition` as dotted-path strings (`"module:attr"`),
  resolved and checked (importable, callable, async) by `validate_registry()` —
  a bad path fails startup, not the first turn. Hook-produced content is
  re-screened by the SAME output guardrail the loop uses. A raising pre-hook
  fails the run (contained); a raising post-hook keeps the original answer and
  records `run.output["post_hook_error"]`. Adding an agent kind must not
  require editing the runtime — that is what the hooks are for.
- Shared Arabic literals (the voice-echo sentinel, the voice marker prefixes)
  live in `constants.py`; producer and matcher import the SAME object. Never
  re-type the string at a second site — the identity test in
  `test_customer_turn.py` exists because a duplicated literal once meant an
  edit on one side silently broke echo-dedup on the other.
- `ai_handovers.reason = "low_confidence"` means: the run HAD evidence (at
  least one tool call) and its reply was still withheld by the grounding
  re-check or the output guardrail. Without tool calls the generic
  `"failure"`/`"guardrail"` reasons apply. §37 promised this reason; the
  producer is the blocked-run mapping in `hooks.py` (mirrored by the eval
  harness in `tests/agent_eval/runner.py` — keep the two in step).
- The SI agent gets ONE regenerate-once when its draft misses a question
  dimension the evidence supports (`agents/sales_intelligence/coverage.py`):
  a gap requires question-asks AND evidence-supports AND answer-silent —
  never demand coverage the evidence cannot back. The regenerated text must
  pass the guardrail, `validate_answer` and a coverage re-check, or the
  original draft and the existing safe-response path apply unchanged.
  Attempted regens are recorded in `run.output["coverage_regen"]`.
- The SI chat turn executor re-binds the tenant after every mid-turn commit;
  COMMIT drops the transaction-local RLS binding and the next query would
  otherwise run tenant-less.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `ai` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
