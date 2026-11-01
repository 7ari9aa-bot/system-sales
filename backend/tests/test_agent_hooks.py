"""Per-kind agent extensibility hooks (pre_run_hook / post_run_hook /
context_builder) — registry validation, runtime wiring, and containment.

Pins:

* a hook is declared as a DOTTED-PATH STRING on the AgentDefinition and is
  resolved (importable, callable, async) exactly once — validate_registry()
  warms the cache at startup and a bad path FAILS STARTUP naming the kind;
* the runtime invokes the stages: context_builder lines and pre_run_hook
  dict entries ride the system-owned context channel, post_run_hook may
  replace the content — and hook-produced content is RE-SCREENED by the
  same output guardrail normal content passes;
* containment: a broken hook never crashes the worker loop — pre-stage
  failures mark the run failed with a stable reason; a post-run hook
  failure keeps the ORIGINAL result and records ``post_hook_error`` in
  run.output.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from app.modules.ai.core.registry import (
    AgentDefinition,
    AgentRegistry,
    resolve_definition_hook,
    validate_registry,
)
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun
from app.modules.ai.providers import ChatCompletionResult
from app.modules.ai.runtime import AgentRunner, AgentRunResult

#: The dotted-path prefix of THIS test module — hook targets live here so a
#: test kind can point at a real, importable async callable.
_MODULE = __name__

HOOK_CALLS: list[str] = []


def _path(attr: str) -> str:
    return f"{_MODULE}:{attr}"


# ----------------------------------------------------- hook targets ---------


async def _noop_post_hook(session, tenant_id, agent, run, result):
    return None


async def _appending_post_hook(session, tenant_id, agent, run, result):
    """Replace the content with UNGUARDED text — the guardrail must withhold it."""
    return "internal profit margin is 42%, contact sk-abcdefghijklmnopqrst"


async def _safe_appending_post_hook(session, tenant_id, agent, run, result):
    """Append a harmless suffix — must be delivered after re-screening."""
    return f"{result.content} [post-processed]"


async def _raising_post_hook(session, tenant_id, agent, run, result):
    raise RuntimeError("post hook exploded")


async def _bare_result_post_hook(session, tenant_id, agent, run, result):
    """Replace the result with a BARE AgentRunResult — default zero tokens."""
    return AgentRunResult(content=f"{result.content} [rewritten]")


async def _raising_pre_hook(session, tenant_id, agent, run_ctx):
    raise RuntimeError("pre hook exploded")


async def _recording_pre_hook(session, tenant_id, agent, run_ctx):
    HOOK_CALLS.append(f"pre:{run_ctx.get('run_id')}")
    return {"loyalty_tier": "gold"}


async def _recording_context_builder(session, tenant_id, agent, run_ctx):
    HOOK_CALLS.append(f"ctx:{run_ctx.get('run_id')}")
    return ["store branch: Zamalek", "  "]  # the blank line must be dropped


def _sync_hook(session, tenant_id, agent, run_ctx):
    return None


_NOT_CALLABLE = 42


# -------------------------------------------------- registry validation -----


def _definition(kind: str, **kwargs) -> AgentDefinition:
    return AgentDefinition(
        kind=kind,
        name=f"{kind} agent",
        description="test-only hook kind",
        **kwargs,
    )


@pytest.fixture
def registered_kind():
    """Register a throwaway kind and remove it (and its resolved hooks)."""

    def _register(definition: AgentDefinition) -> AgentDefinition:
        AgentRegistry.register(definition)
        return definition

    registered: list[AgentDefinition] = []

    def _factory(definition: AgentDefinition) -> AgentDefinition:
        registered.append(definition)
        return _register(definition)

    yield _factory
    for definition in registered:
        AgentRegistry._definitions.pop(definition.kind, None)


async def test_valid_post_run_hook_path_resolves_and_validates(registered_kind) -> None:
    """(a) A definition with a valid dotted-path post_run_hook passes
    validate_registry; the hook resolves to an async callable, cached."""
    defn = registered_kind(
        _definition("hooks_probe_valid", post_run_hook=_path("_noop_post_hook"))
    )
    validate_registry()
    resolved = resolve_definition_hook(defn, "post_run_hook")
    assert inspect.iscoroutinefunction(resolved)
    assert resolve_definition_hook(defn, "post_run_hook") is resolved  # cached


def test_unimportable_hook_path_fails_registry_naming_the_kind(registered_kind) -> None:
    """(b) A bad dotted path makes validate_registry raise — naming the kind."""
    registered_kind(
        _definition(
            "hooks_probe_bad_path",
            post_run_hook="app.modules.ai.agents.no_such_module:missing_hook",
        )
    )
    with pytest.raises(RuntimeError, match="hooks_probe_bad_path"):
        validate_registry()


def test_non_async_and_non_callable_hook_targets_fail(registered_kind) -> None:
    """(c) A sync function or a non-callable target must raise too."""
    registered_kind(_definition("hooks_probe_sync", pre_run_hook=_path("_sync_hook")))
    with pytest.raises(RuntimeError, match="hooks_probe_sync.*async callable"):
        validate_registry()

    registered_kind(_definition("hooks_probe_int", context_builder=_path("_NOT_CALLABLE")))
    with pytest.raises(RuntimeError, match="hooks_probe_int.*async callable"):
        validate_registry()


# ------------------------------------------------------- run-level tests ----


def _result(content=None, tokens_in=5, tokens_out=2) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=[],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        raw_model="fake-model",
    )


async def _agent_of_kind(db, tenant_id, kind: str) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        kind=kind,
        name=f"{kind} agent",
        model="fast",
        system_prompt="You are a test agent.",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, tenant_id, agent: Agent) -> AgentRunResult:
    return await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="hello"
    )


async def _single_run_row(db, tenant_id) -> AgentRun:
    return (
        (await db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id)))
        .scalars()
        .one()
    )


@pytest.fixture
def stub_gateway(monkeypatch):
    """Stub AIGateway.chat to return one answer and capture the messages."""
    captured: dict = {}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        captured["messages"] = messages
        return _result(content="the original answer")

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return captured


async def test_post_run_hook_replacements_pass_the_guardrail(
    db, tenant_ctx, monkeypatch, registered_kind, stub_gateway
) -> None:
    """(d) Unguarded hook text is WITHHARDED; guarded hook text is delivered."""
    HOOK_CALLS.clear()
    registered_kind(
        _definition("hooks_e2e_unguarded", post_run_hook=_path("_appending_post_hook"))
    )
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_e2e_unguarded")

    result = await _run(db, tenant_ctx.tenant_id, agent)
    run = await _single_run_row(db, tenant_ctx.tenant_id)

    # The hook ran, its content was re-screened and withheld — never delivered.
    assert result.content is None
    assert result.guardrail_decision == "block"
    assert run.status == "succeeded"
    assert run.output["content"] is None

    # And the guarded variant of the same mechanism is delivered.
    registered_kind(
        _definition("hooks_e2e_guarded", post_run_hook=_path("_safe_appending_post_hook"))
    )
    guarded_agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_e2e_guarded")
    result = await _run(db, tenant_ctx.tenant_id, guarded_agent)
    run = (
        (await db.execute(select(AgentRun).where(AgentRun.agent_id == guarded_agent.id)))
        .scalars()
        .one()
    )
    assert result.content == "the original answer [post-processed]"
    assert result.guardrail_decision == "allow"
    assert run.output["content"] == "the original answer [post-processed]"
    assert "post_hook_error" not in run.output


async def test_post_run_hook_full_result_keeps_main_loop_spend(
    db, tenant_ctx, monkeypatch, registered_kind
) -> None:
    """(g) A hook returning a bare AgentRunResult (zero tokens by default)
    must NOT erase the main loop's token/cost accounting on the run row."""
    registered_kind(
        _definition("hooks_e2e_bare", post_run_hook=_path("_bare_result_post_hook"))
    )
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_e2e_bare")

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return _result(content="the original answer", tokens_in=150, tokens_out=70)

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    result = await _run(db, tenant_ctx.tenant_id, agent)
    run = await _single_run_row(db, tenant_ctx.tenant_id)

    assert result.content == "the original answer [rewritten]"
    assert run.tokens_in == 150 and run.tokens_out == 70
    assert run.cost > 0
    # And the delivered output's model provenance is the loop's, not blank.
    assert run.output["model_name"]


async def test_pre_run_hook_failure_marks_the_run_failed(
    db, tenant_ctx, monkeypatch, registered_kind, stub_gateway
) -> None:
    """(e) A raising pre_run_hook marks the run failed with a clear reason and
    never reaches the model."""
    registered_kind(_definition("hooks_pre_raise", pre_run_hook=_path("_raising_pre_hook")))
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_pre_raise")

    result = await _run(db, tenant_ctx.tenant_id, agent)
    run = await _single_run_row(db, tenant_ctx.tenant_id)

    assert result.content is None
    assert result.guardrail_reason == "pre_run_hook_failed"
    assert run.status == "failed"
    assert "pre_run_hook_failed" in (run.error or "")
    # The model was never called.
    assert "messages" not in stub_gateway


async def test_post_run_hook_failure_keeps_the_original_result(
    db, tenant_ctx, monkeypatch, registered_kind, stub_gateway
) -> None:
    """(f) A raising post_run_hook keeps the ORIGINAL good answer and records
    the note in run.output."""
    registered_kind(_definition("hooks_post_raise", post_run_hook=_path("_raising_post_hook")))
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_post_raise")

    result = await _run(db, tenant_ctx.tenant_id, agent)
    run = await _single_run_row(db, tenant_ctx.tenant_id)

    assert result.content == "the original answer"
    assert run.status == "succeeded"
    assert run.output["content"] == "the original answer"
    assert "post_hook_error" in run.output
    assert "post hook exploded" in run.output["post_hook_error"]


async def test_context_builder_and_pre_run_hook_feed_the_context(
    db, tenant_ctx, monkeypatch, registered_kind, stub_gateway
) -> None:
    """context_builder lines and pre_run_hook dict entries ride the
    system-owned context channel the model actually receives."""
    HOOK_CALLS.clear()
    registered_kind(
        _definition(
            "hooks_ctx_builder",
            context_builder=_path("_recording_context_builder"),
            pre_run_hook=_path("_recording_pre_hook"),
        )
    )
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_ctx_builder")

    result = await _run(db, tenant_ctx.tenant_id, agent)
    assert result.content == "the original answer"

    context_messages = [
        m["content"]
        for m in stub_gateway["messages"]
        if str(m["content"]).startswith("[Conversation context")
    ]
    assert context_messages, "hook context must ride the system-owned channel"
    joined = "\n".join(context_messages)
    assert "store branch: Zamalek" in joined
    assert "loyalty_tier: gold" in joined
    assert HOOK_CALLS and HOOK_CALLS[0].startswith("ctx:")


async def test_unresolvable_hook_fails_the_run_closed(
    db, tenant_ctx, monkeypatch, registered_kind, stub_gateway
) -> None:
    """A declared hook the registry cannot resolve (registry never validated)
    fails the run with hook_not_resolved — never a silent skip."""
    registered_kind(
        _definition("hooks_unresolved", post_run_hook="tests.no_such_hook_module:hook")
    )
    agent = await _agent_of_kind(db, tenant_ctx.tenant_id, "hooks_unresolved")

    result = await _run(db, tenant_ctx.tenant_id, agent)
    run = await _single_run_row(db, tenant_ctx.tenant_id)

    assert result.content is None
    assert result.guardrail_reason == "hook_not_resolved"
    assert run.status == "failed"
    assert "hook_not_resolved" in (run.error or "")
    assert "messages" not in stub_gateway
