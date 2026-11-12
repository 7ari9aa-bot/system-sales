"""SI orchestrator tests (spec §2.2, Phase 7 v1) — real DB, mocked model.

The happy path: the model investigates with the SI tools and answers with
tool-backed numbers. The rejection path: one free number in the answer and
the SAFE RESPONSE replaces it — deterministic, findings-based, no third
model call. The tools themselves are the platform registry's, so the
runner's tool loop exercises them end-to-end.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.ai.agents.sales_intelligence.coverage import (
    build_corrective_instruction,
    coverage_gaps,
    regenerate_on_coverage_gap,
)
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun, AgentTool
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.customers.models import Customer
from app.modules.orders.models import Order


def _patch_gateway(monkeypatch, results) -> dict:
    calls = {"count": 0, "list": []}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["list"].append({"tools": tools})
        return results[min(calls["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


def _recording_gateway(monkeypatch, results, fail_on: set[int] | None = None):
    """Stub the gateway, recording every call (alias, messages, tools)."""
    calls: list[dict] = []
    state = {"count": 0}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        state["count"] += 1
        if fail_on and state["count"] in fail_on:
            raise RuntimeError("regen boom")
        calls.append({"alias": alias, "messages": messages, "tools": tools})
        return results[min(state["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls, state


async def _run_row(db, run_id) -> AgentRun:
    return await db.get(AgentRun, run_id)


async def _seed(db, tenant_id, agent_with_tools: bool = True):
    # The agent always exists (the run is addressed to it); ``agent_with_tools`` only decides
    # whether the si_* tools are granted to it.
    agent = Agent(
        tenant_id=tenant_id,
        name="SI Agent",
        model="fast",
        system_prompt="analyze",
        # The registry gates si_* tools by agent kind; the server default
        # ("customer") is fail-closed for them — 'denied', not 'error'.
        kind="sales_intelligence",
    )
    db.add(agent)
    await db.flush()
    if agent_with_tools:
        for name in (
            "si_get_metric",
            "si_compare_periods",
            "si_breakdown",
            "si_analyze_drivers",
        ):
            db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name))
    customer = Customer(tenant_id=tenant_id, name="SI Customer")
    db.add(customer)
    await db.flush()
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    db.add(
        Order(
            tenant_id=tenant_id,
            number=f"O-{uuid.uuid4().hex[:8]}",
            customer_id=customer.id,
            status="fulfilled",
            grand_total=1200.0,
            channel="web",
            placed_at=today - timedelta(days=5),
        )
    )
    await db.flush()
    return agent


async def test_si_tools_registered_in_the_platform_registry():
    from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
    from app.modules.ai.tools import TOOLS

    # A fixed count here went stale with every new tool. What must hold is that the tools that
    # are REGISTERED and the tools the agent is ALLOWED to call are the same set: a tool that is
    # registered but missing from SI_TOOLS is refused by the agent without any error.
    si_tools = sorted(n for n in TOOLS if n.startswith("si_"))
    assert si_tools == sorted(SI_TOOLS)
    assert len(si_tools) >= 13


async def test_orchestrator_rejects_a_free_number_with_the_safe_response(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    # The model investigates with a real tool, then answers with a number
    # NO tool produced (99) — the safe response must replace it.
    results = [
        ChatCompletionResult(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="si_get_metric",
                    arguments={"metric_name": "orders_placed", "days": 30},
                )
            ],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        ),
        ChatCompletionResult(
            content="المبيعات 1200 EGP وده رغم إن الهدف كان 99",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        ),
    ]
    _patch_gateway(monkeypatch, results)

    result = await run_sales_analysis(
        db, tenant_id, agent_id=agent.id, question="كام مبيعات الشهر ده؟"
    )

    # The runner's evidence guardrail blocks the unsourced 99 BEFORE the
    # SI response gate — defense in depth; either way it never survives.
    # As a whole number, not as two digits: the answer can carry evidence JSON whose timestamps
    # hold "99" by chance (a microsecond field), which made this assertion fail one run in a while.
    assert not re.search(r"(?<![\d.:-])99(?![\d.:-])", result.answer), (
        "the free number never survives"
    )
    assert result.outcome.value in ("ANSWERED", "INSUFFICIENT_DATA")
    assert result.findings == []  # one metric alone makes no change finding


async def test_grounded_answer_passes_through(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    results = [
        ChatCompletionResult(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="si_get_metric",
                    arguments={"metric_name": "orders_placed", "days": 30},
                )
            ],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        ),
        ChatCompletionResult(
            content="عدد الطلبات الموضوعة الشهر ده: 1",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        ),
    ]
    _patch_gateway(monkeypatch, results)

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question="كام طلب؟")
    assert result.outcome.value == "ANSWERED"
    assert result.answer == "عدد الطلبات الموضوعة الشهر ده: 1"
    assert "1" in " ".join(str(p["value"]) for p in result.facts)


async def test_the_si_agent_runs_the_prompt_stored_on_its_row(db, tenant_ctx, monkeypatch):
    """The agent's own row governs the system prompt — nothing hardcoded here.

    `run_sales_analysis` used to pass `SI_SYSTEM_PROMPT` as an override, and
    `_resolve_system_prompt` ranks an override ABOVE the agent row. So the whole
    Sales Intelligence agent ran on a constant: the stored configuration, a
    merchant editing the prompt in the UI, and any future prompt rollout could
    not change one byte of what the model was told.
    """
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    assert agent.system_prompt == "analyze"

    seen: list[list[dict]] = []

    async def fake_chat(self, session, tid, *, alias, messages, tools=None, **kwargs):  # noqa: ANN001
        seen.append(messages)
        return ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    await run_sales_analysis(db, tenant_id, agent_id=agent.id, question="كام طلب؟")

    assert seen, "the model was never called"
    system_message = seen[0][0]
    assert system_message["role"] == "system"
    assert system_message["content"] == "analyze", (
        "the row must govern: an override here makes the stored prompt, every "
        "merchant edit, and any prompt rollout inert for this agent"
    )


async def test_no_tool_results_still_answers_safely(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content="مش عارف", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            )
        ],
    )
    result = await run_sales_analysis(
        db, tenant_id, agent_id=agent.id, question="ليه المبيعات قلت؟"
    )
    assert result.outcome.value == "ANSWERED"
    assert result.answer == "مش عارف"


async def test_unknown_metric_fails_the_tool_loudly(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    results = [
        ChatCompletionResult(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="si_get_metric",
                    arguments={"metric_name": "profit_margin"},
                )
            ],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        ),
        ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        ),
    ]
    _patch_gateway(monkeypatch, results)

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question="المكسب؟")
    # The tool call FAILED loudly (unknown metric) — the run continued, but
    # no fact was fabricated: the facts list stays empty.
    assert result.facts == []
    metric_call = next(c for c in result.tool_calls_made if c["name"] == "si_get_metric")
    assert metric_call["status"] == "error"


async def test_failed_run_emits_the_failed_analysis_event(db, tenant_ctx):
    """A started event with no counterpart reads as 'stuck forever' to
    anything pairing them — the run failure now emits ai.analysis.failed
    (same transaction, best-effort) before re-raising."""
    import pytest
    from sqlalchemy import select as sa_select

    from app.modules.platform.models import OutboxEvent

    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id, agent_with_tools=False)

    class _Boom:
        async def run(self, *args, **kwargs):
            raise RuntimeError("gateway down")

    with pytest.raises(RuntimeError, match="gateway down"):
        await run_sales_analysis(db, tenant_id, agent_id=agent.id, question="سؤال", runner=_Boom())

    rows = (
        (
            await db.execute(
                # The outbox table has no tenant/type columns: both ride inside the JSONB.
                sa_select(OutboxEvent).where(
                    OutboxEvent.meta["tenant_id"].astext == str(tenant_id),
                    OutboxEvent.payload["event_type"].astext == "ai.analysis.failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


# ───────────────────────────── between-rounds coverage + regenerate-once ──

_TWO_DIM_QUESTION = "كام مبيعات وكام طلبات الشهر ده؟"
_TOOL_ROUND = ChatCompletionResult(
    content=None,
    tool_calls=[
        ToolCallRequest(
            id="c1",
            name="si_get_metric",
            arguments={"metric_name": "orders_placed", "days": 30},
        )
    ],
    tokens_in=1,
    tokens_out=1,
    raw_model="m",
)


async def test_coverage_gap_triggers_exactly_one_corrective_regen(db, tenant_ctx, monkeypatch):
    """(a) The first answer skips a dimension the question asked for and the
    evidence supports → ONE regeneration, instructed in Arabic naming the
    gap, tools disabled → the regenerated answer ships and the run row
    records the payoff."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    calls, state = _recording_gateway(
        monkeypatch,
        [
            _TOOL_ROUND,
            # Addresses orders only — "sales" is uncovered though supported.
            ChatCompletionResult(
                content="عدد الطلبات الموضوعة الشهر ده: 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            # The regenerated answer covers the named gap, tool-backed numbers.
            ChatCompletionResult(
                content="المبيعات الشهر ده قيمة الطلبات الموضوعة: 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
        ],
    )

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question=_TWO_DIM_QUESTION)

    # The loop made 2 calls; exactly ONE extra corrective call happened.
    assert state["count"] == 3
    regen = calls[2]
    assert regen["tools"] is None, "the correction must reuse gathered evidence only"
    roles = [m["role"] for m in regen["messages"]]
    assert roles == ["system", "assistant", "user"]
    instruction = regen["messages"][-1]["content"]
    assert "المبيعات" in instruction, "the instruction names the uncovered dimension"
    assert "ممنوع" in instruction, "the instruction forbids inventing numbers"
    assert "99" not in instruction

    assert result.answer == "المبيعات الشهر ده قيمة الطلبات الموضوعة: 1"
    assert result.outcome.value == "ANSWERED"

    run = await _run_row(db, result.run_id)
    note = run.output["coverage_regen"]
    assert note["attempted"] is True
    assert note["succeeded"] is True
    assert note["gaps"] == ["sales"]


async def test_failed_regen_keeps_the_original_and_never_a_wrong_number(
    db, tenant_ctx, monkeypatch
):
    """(b) The regen answer invents a number (500) → discarded, the ORIGINAL
    draft continues down the normal validation path, and the run row records
    the failed attempt. No number outside the evidence appears anywhere."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    _recording_gateway(
        monkeypatch,
        [
            _TOOL_ROUND,
            ChatCompletionResult(
                content="عدد الطلبات الموضوعة الشهر ده: 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
            ChatCompletionResult(
                content="المبيعات وصلت 500 والطلبات 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
        ],
    )

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question=_TWO_DIM_QUESTION)

    assert result.answer == "عدد الطلبات الموضوعة الشهر ده: 1"
    assert result.outcome.value == "ANSWERED"
    assert "500" not in result.answer

    run = await _run_row(db, result.run_id)
    note = run.output["coverage_regen"]
    assert note["attempted"] is True
    assert note["succeeded"] is False
    assert note["gaps"] == ["sales"]


async def test_regen_gateway_failure_keeps_the_original(db, tenant_ctx, monkeypatch):
    """(d) The regen model call raises → the original draft is kept, the
    attempt is recorded, and the orchestrator path is unaffected."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    _recording_gateway(
        monkeypatch,
        [
            _TOOL_ROUND,
            ChatCompletionResult(
                content="عدد الطلبات الموضوعة الشهر ده: 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
        ],
        fail_on={3},
    )

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question=_TWO_DIM_QUESTION)

    assert result.answer == "عدد الطلبات الموضوعة الشهر ده: 1"
    run = await _run_row(db, result.run_id)
    note = run.output["coverage_regen"]
    assert note["attempted"] is True
    assert note["succeeded"] is False


async def test_covered_answer_makes_zero_extra_model_calls(db, tenant_ctx, monkeypatch):
    """(c) The first answer addresses everything the question asked and the
    evidence supports → no regen, no coverage_regen note, nothing spent."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    _, state = _recording_gateway(
        monkeypatch,
        [
            _TOOL_ROUND,
            ChatCompletionResult(
                content="عدد الطلبات الموضوعة الشهر ده: 1",
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            ),
        ],
    )

    result = await run_sales_analysis(db, tenant_id, agent_id=agent.id, question="كام طلب؟")

    assert state["count"] == 2, "tool round + answer, nothing else"
    run = await _run_row(db, result.run_id)
    assert "coverage_regen" not in run.output


# ────────────────────────────────────── coverage unit tests ──

_ORDERS_EVIDENCE = {"facts": [{"metric": "orders_placed", "value": 5}]}


def test_coverage_gaps_empty_on_a_complete_answer():
    gaps = coverage_gaps("كام مبيعات الشهر ده؟", "المبيعات الشهر ده: 5", _ORDERS_EVIDENCE)
    assert gaps == []


def test_coverage_gaps_detects_the_skipped_dimension():
    # The question asks sales AND orders; the answer covers orders only.
    gaps = coverage_gaps("كام مبيعات وكام طلبات؟", "عدد الطلبات: 5", _ORDERS_EVIDENCE)
    assert gaps == ["sales"]


def test_coverage_gaps_skips_unsupported_dimensions():
    # Fulfillment is asked about but the evidence carries no carrier data —
    # demanding it would push the model into inventing.
    gaps = coverage_gaps("إيه حالة الشحن والتسليم؟", "الطلبات كتير الشهر ده", _ORDERS_EVIDENCE)
    assert gaps == []


def test_coverage_gaps_empty_answer_reports_every_supported_dimension():
    assert coverage_gaps("كام مبيعات الشهر ده؟", None, _ORDERS_EVIDENCE) == ["sales"]
    # And an empty evidence pack supports nothing.
    assert coverage_gaps("كام مبيعات الشهر ده؟", None, {}) == []


def test_coverage_gaps_ignores_unrelated_questions():
    assert coverage_gaps("مرحبا", "أهلاً بييك", _ORDERS_EVIDENCE) == []


def test_corrective_instruction_names_the_gaps_and_forbids_new_numbers():
    instruction = build_corrective_instruction(["sales", "fulfillment"])
    assert "المبيعات" in instruction
    assert "الشحن" in instruction
    assert "ممنوع" in instruction


async def test_si_definition_still_resolves_with_the_coverage_module_wired():
    """Pin: the SI kind registers, and the coverage module the orchestrator
    depends on exposes the exact callables the wiring uses."""
    from app.modules.ai.agents.sales_intelligence import coverage as coverage_module
    from app.modules.ai.core.registry import AgentRegistry

    defn = AgentRegistry.get("sales_intelligence")
    assert defn.kind == "sales_intelligence"
    assert coverage_module.coverage_gaps is coverage_gaps
    assert callable(coverage_module.regenerate_on_coverage_gap)


# ───────────────────────────── regenerate_on_coverage_gap, DB-free ──


class _FakeSession:
    def __init__(self, agent):
        self._agent = agent

    async def get(self, model, obj_id):
        return self._agent


def _stub_agent():
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid.uuid4(),
        kind="sales_intelligence",
        model="fast",
        system_prompt="analyze",
        temperature=0.2,
        max_output_tokens=200,
    )


async def test_regen_unit_success_replaces_the_draft(monkeypatch):
    """The happy regen: one gateway call (tools=None) instructed in Arabic
    naming the gap; the candidate passes the gates and replaces the draft."""
    agent = _stub_agent()
    captured: list[dict] = []

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        captured.append({"alias": alias, "messages": messages, "tools": tools})
        return ChatCompletionResult(
            content="المبيعات قيمة الطلبات الموضوعة: 5",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    replacement, note, regen_tokens = await regenerate_on_coverage_gap(
        _FakeSession(agent),
        uuid.uuid4(),
        agent_id=agent.id,
        run_id=None,
        question="كام مبيعات وكام طلبات؟",
        history=None,
        draft="عدد الطلبات: 5",
        evidence={"facts": [{"metric": "orders_placed", "value": 5}]},
        allowed_numbers={"5"},
        findings=[],
        tool_calls_made=[],
    )

    assert note == {"attempted": True, "succeeded": True, "gaps": ["sales"]}
    assert replacement == "المبيعات قيمة الطلبات الموضوعة: 5"
    assert len(captured) == 1
    assert captured[0]["tools"] is None
    assert "المبيعات" in captured[0]["messages"][-1]["content"]


async def test_regen_unit_rejects_an_invented_number(monkeypatch):
    """The regen draft carries a number no tool produced → discarded, the
    original draft is kept, and the note records the failed attempt."""
    agent = _stub_agent()

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return ChatCompletionResult(
            content="المبيعات وصلت 500 والطلبات 5",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)

    replacement, note, regen_tokens = await regenerate_on_coverage_gap(
        _FakeSession(agent),
        uuid.uuid4(),
        agent_id=agent.id,
        run_id=None,
        question="كام مبيعات وكام طلبات؟",
        history=None,
        draft="عدد الطلبات: 5",
        evidence={"facts": [{"metric": "orders_placed", "value": 5}]},
        allowed_numbers={"5"},
        findings=[],
        tool_calls_made=[],
    )

    assert replacement is None
    assert note == {"attempted": True, "succeeded": False, "gaps": ["sales"]}


async def test_the_askers_permissions_reach_the_runner(db, tenant_ctx, monkeypatch):
    """``run_sales_analysis`` is the last hop between the chat and the runner. If it drops
    ``actor_permissions`` the runner sees an unknown asker, and every permission-gated tool
    silently disappears for the OWNER too. The chat-level test mocks this function away, so only
    a test through it can see the loss."""
    from app.modules.ai.runtime import AgentRunner

    tenant_id = tenant_ctx.tenant_id
    agent = await _seed(db, tenant_id)
    seen: dict = {}
    real_run = AgentRunner.run

    async def spy(self, *args, **kwargs):
        seen["actor_permissions"] = kwargs.get("actor_permissions", "NOT PASSED")
        return await real_run(self, *args, **kwargs)

    monkeypatch.setattr(AgentRunner, "run", spy)
    _patch_gateway(
        monkeypatch,
        [
            ChatCompletionResult(
                content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
            )
        ],
    )

    await run_sales_analysis(
        db,
        tenant_id,
        agent_id=agent.id,
        question="كام طلب؟",
        actor_permissions={"analytics:read", "finance:read"},
    )

    assert seen["actor_permissions"] == {"analytics:read", "finance:read"}
