"""AgentRunner tests — tool loop, policy enforcement, run/tool_call records."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun, AgentTool, AIUsage, ToolCall
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.tools import get_tool, tool_to_openai_schema
from app.modules.catalog.models import Product, ProductVariant
from app.modules.errors import NotFoundError as ModuleNotFoundError
from app.modules.inventory.models import InventoryBalance, Warehouse


def _result(content=None, tool_calls=None, tokens_in=0, tokens_out=0) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=tool_calls or [],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        raw_model="fake-model",
    )


async def _agent_with_tool(db, tenant_id, *, name="search_products", policy=None) -> Agent:
    agent = Agent(
        tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="You sell things."
    )
    db.add(agent)
    await db.flush()
    db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name, policy=policy or {}))
    await db.flush()
    return agent


async def _seed_variant(db, tenant_id):
    product = Product(
        tenant_id=tenant_id, title="Blue Widget", slug=f"bw-{uuid.uuid4().hex[:8]}"
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"BW-{uuid.uuid4().hex[:6].upper()}",
        title="Blue Widget M",
        price=Decimal("25.50"),
    )
    db.add(variant)
    await db.flush()
    return variant


def _patch_gateway_chat(monkeypatch, results: list[ChatCompletionResult]) -> dict:
    calls = {"count": 0, "tools": None, "messages": None}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["tools"] = tools
        calls["messages"] = messages
        return results[min(calls["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


# ---------------------------------------------------------------- runtime ---


async def test_agent_run_calls_tool_then_answers(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with_tool(db, tenant_id)
    variant = await _seed_variant(db, tenant_id)

    results = [
        _result(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="search_products",
                    arguments={"query": "widget", "limit": 5},
                )
            ],
            tokens_in=10,
        ),
        _result(content="Found it — Blue Widget M is 25.5.", tokens_in=30, tokens_out=8),
    ]
    calls = _patch_gateway_chat(monkeypatch, results)

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="how much is the widget?"
    )

    assert result.content == "Found it — Blue Widget M is 25.5."
    assert result.tokens_in == 40
    assert result.tokens_out == 8
    assert [(tc["name"], tc["status"]) for tc in result.tool_calls_made] == [
        ("search_products", "ok")
    ]

    # The tool schema was advertised and the follow-up request carried the
    # tool result message.
    assert calls["tools"] is not None
    assert calls["tools"][0]["function"]["name"] == "search_products"
    assert any(m["role"] == "tool" for m in calls["messages"])

    run = (
        (await db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert run.status == "succeeded"
    assert run.tokens_in == 40
    assert run.tokens_out == 8
    assert run.output["content"] == result.content
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.error is None

    tc_row = (
        (await db.execute(select(ToolCall).where(ToolCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert tc_row.run_id == run.id
    assert tc_row.name == "search_products"
    assert tc_row.status == "ok"
    assert tc_row.agent_tool_id is not None
    assert tc_row.args == {"query": "widget", "limit": 5}
    assert tc_row.result["results"][0]["variant_id"] == str(variant.id)
    assert tc_row.result["results"][0]["sku"] == variant.sku
    assert tc_row.result["results"][0]["price"] == 25.5
    assert tc_row.duration_ms is not None

    # Usage rollup written by the finalize step.
    usage = (
        (await db.execute(select(AIUsage).where(AIUsage.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert usage.agent_id == agent.id
    assert usage.tokens_in == 40
    assert usage.tokens_out == 8
    assert usage.model_calls == 1


async def test_agent_run_uses_configured_step_limit(db, tenant_ctx, monkeypatch):
    agent = await _agent_with_tool(db, tenant_ctx.tenant_id)
    agent.run_limits = {"max_steps": 1}
    await db.flush()

    calls = _patch_gateway_chat(
        monkeypatch,
        [
            _result(
                tool_calls=[
                    ToolCallRequest(
                        id="limited_call",
                        name="search_products",
                        arguments={"query": "widget"},
                    )
                ]
            ),
            _result(content="should not run"),
        ],
    )

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_ctx.tenant_id, agent_id=agent.id, user_message="search"
    )

    assert calls["count"] == 1
    assert result.content is None

    run = (
        (await db.execute(select(AgentRun).where(AgentRun.agent_id == agent.id)))
        .scalars()
        .one()
    )
    assert run.status == "timeout"
    assert run.error == "run limit hit: max_steps"


async def test_agent_run_denies_tool_by_policy(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with_tool(db, tenant_id, policy={"denied": ["search_products"]})

    results = [
        _result(
            tool_calls=[
                ToolCallRequest(id="c1", name="search_products", arguments={"query": "x"})
            ]
        ),
        _result(content="I cannot check the catalog.", tokens_in=5, tokens_out=2),
    ]
    _patch_gateway_chat(monkeypatch, results)

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="search"
    )

    assert result.tool_calls_made[0]["status"] == "denied"
    assert result.content == "I cannot check the catalog."

    tc_row = (
        (await db.execute(select(ToolCall).where(ToolCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert tc_row.status == "denied"
    assert tc_row.error == "tool denied by policy"
    assert tc_row.result is None

    run = (
        (await db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert run.status == "succeeded"


async def test_agent_run_denies_tool_not_enabled_for_agent(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = Agent(tenant_id=tenant_id, name="No Tools", model="fast")
    db.add(agent)
    await db.flush()

    results = [
        _result(
            tool_calls=[ToolCallRequest(id="c1", name="check_stock", arguments={})]
        ),
        _result(content="Sorry, no tools.", tokens_in=3, tokens_out=1),
    ]
    _patch_gateway_chat(monkeypatch, results)

    result = await AgentRunner(gateway=AIGateway()).run(
        db, tenant_id, agent_id=agent.id, user_message="stock?"
    )

    assert result.tool_calls_made[0]["status"] == "denied"
    tc_row = (
        (await db.execute(select(ToolCall).where(ToolCall.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert tc_row.status == "denied"
    assert tc_row.error == "tool not enabled for this agent"
    assert tc_row.agent_tool_id is None


async def test_agent_run_failed_on_gateway_error(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent_with_tool(db, tenant_id)

    async def boom(self, session, tenant_id, **kwargs):
        raise NotFoundError("no model configured for alias fast")

    monkeypatch.setattr(AIGateway, "chat", boom)
    with pytest.raises(NotFoundError):
        await AgentRunner(gateway=AIGateway()).run(
            db, tenant_id, agent_id=agent.id, user_message="hi"
        )

    run = (
        (await db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert run.status == "failed"
    assert "no model configured" in run.error
    assert run.finished_at is not None


async def test_run_unknown_agent_raises_not_found(db, tenant_ctx):
    with pytest.raises(NotFoundError):
        await AgentRunner().run(
            db, tenant_ctx.tenant_id, agent_id=uuid.uuid4(), user_message="hi"
        )


# ------------------------------------------------------------------ tools ---


def test_core_tools_are_registered():
    for name in ("search_products", "get_variant_price", "check_stock", "create_order"):
        spec = get_tool(name)
        assert spec is not None
        assert spec.name == name
        assert spec.description
        assert spec.args_schema is not None
        assert spec.handler is not None


def test_create_order_tool_registered_without_orders_dependency():
    # The tool is registered at import time; the handler only imports
    # OrderService lazily so the registry works even without the module.
    spec = get_tool("create_order")
    assert spec is not None
    schema = tool_to_openai_schema(spec)
    assert schema["type"] == "function"
    properties = schema["function"]["parameters"]["properties"]
    # §132: the model must NEVER choose the customer — the server pins it
    # to the conversation scope; only items are model-chosen.
    assert "customer_id" not in properties
    assert "items" in properties


async def test_check_stock_tool_sums_across_warehouses(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    variant = await _seed_variant(db, tenant_id)
    warehouse = Warehouse(
        tenant_id=tenant_id, name="WH", code=f"W-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            variant_id=variant.id,
            on_hand=10,
            reserved=3,
        )
    )
    await db.flush()

    spec = get_tool("check_stock")
    kwargs = spec.args_schema(variant_id=str(variant.id)).model_dump()
    result = await spec.handler(db, tenant_id, **kwargs)
    assert result["available"] == 7
    assert result["sku"] == variant.sku


async def test_get_variant_price_unknown_raises(db, tenant_ctx):
    spec = get_tool("get_variant_price")
    with pytest.raises(ModuleNotFoundError):
        await spec.handler(db, tenant_ctx.tenant_id, variant_id=str(uuid.uuid4()))
