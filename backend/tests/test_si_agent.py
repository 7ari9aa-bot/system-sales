"""SI orchestrator tests (spec §2.2, Phase 7 v1) — real DB, mocked model.

The happy path: the model investigates with the SI tools and answers with
tool-backed numbers. The rejection path: one free number in the answer and
the SAFE RESPONSE replaces it — deterministic, findings-based, no third
model call. The tools themselves are the platform registry's, so the
runner's tool loop exercises them end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool
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


async def _seed(db, tenant_id, agent_with_tools: bool = True):
    if agent_with_tools:
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
    from app.modules.ai.tools import TOOLS

    si_tools = sorted(n for n in TOOLS if n.startswith("si_"))
    assert len(si_tools) == 9


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
    assert "99" not in result.answer, "the free number never survives"
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
