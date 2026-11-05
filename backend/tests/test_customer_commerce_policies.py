"""Exact published policies and read-only deposit facts for the customer agent.

DB tests use real tenant-scoped reads; only the embedding boundary is replaced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.modules.ai import knowledge, policies
from app.modules.ai.agents.customer.grounding import check_grounding
from app.modules.ai.agents.customer.ledger import facts_from_tool_calls
from app.modules.ai.agents.customer.tools.store import GetStoreInfoArgs
from app.modules.ai.models import KnowledgeItem
from app.modules.ai.tools import get_tool, tool_to_openai_schema
from app.modules.identity.models import Tenant
from app.modules.orders.deposit_service import DepositService


@pytest.fixture
def unavailable_embeddings(monkeypatch):
    async def unavailable(session, tenant_id, texts):
        raise ValidationError("embedding provider unavailable")

    monkeypatch.setattr(knowledge, "_embed", unavailable)


def test_schema_keeps_one_store_tool_with_optional_topic_and_question():
    spec = get_tool("get_store_info")
    schema = tool_to_openai_schema(spec)["function"]["parameters"]
    assert set(schema["properties"]) == {"topic", "question"}
    assert schema["additionalProperties"] is False
    assert not schema.get("required")
    assert spec.args_schema is GetStoreInfoArgs
    assert spec.args_schema().model_dump() == {"topic": "all", "question": None}


@pytest.mark.parametrize(
    "topic",
    ["all", "exchange", "return", "shipping", "hours", "ordering", "cancellation", "deposit"],
)
def test_schema_accepts_only_supported_topics(topic):
    assert GetStoreInfoArgs(topic=topic, question="What is the policy?").topic == topic


@pytest.mark.parametrize("topic", ["warranty", "RETURN", "", None, 1, ["deposit"]])
def test_schema_rejects_unknown_or_non_string_topics(topic):
    with pytest.raises(PydanticValidationError):
        GetStoreInfoArgs(topic=topic)


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": str(uuid.uuid4())},
        {"customer_id": str(uuid.uuid4())},
        {"currency": "USD"},
        {"visibility": "staff_only"},
        {"order_id": str(uuid.uuid4())},
        {"order_amount": "1000"},
        {"deposit_value": "1"},
        {"unknown": "value"},
    ],
)
def test_schema_rejects_scope_and_commerce_overrides(extra):
    with pytest.raises(PydanticValidationError):
        GetStoreInfoArgs(topic="deposit", **extra)


async def _info(db, tenant_id, **kwargs):
    return await get_tool("get_store_info").handler(db, tenant_id, **kwargs)


def _facts(info):
    return facts_from_tool_calls([{"name": "get_store_info", "status": "ok", "result": info}])


async def test_exact_policy_beyond_thirty_rows_ignores_unavailable_search(
    db, tenant_ctx, unavailable_embeddings
):
    tenant_id = tenant_ctx.tenant_id
    old = datetime(2020, 1, 1, tzinfo=UTC)
    db.add_all(
        KnowledgeItem(
            tenant_id=tenant_id,
            title=f"Unrelated {i}",
            content="General store information.",
            source_type="text",
            created_at=old + timedelta(seconds=i),
        )
        for i in range(35)
    )
    await db.flush()
    await policies.save_policy(db, tenant_id, "return", "الاسترجاع خلال 14 يوم.")

    # The default list cannot reach the newer policy within its row cap.
    default = await _info(db, tenant_id)
    assert len(default["items"]) == 30 and default["truncated"] is True
    assert all(i["content"] != "الاسترجاع خلال 14 يوم." for i in default["items"])

    exact = await _info(db, tenant_id, topic="return", question="What about returns?")
    assert [(i["title"], i["content"]) for i in exact["items"]] == [
        ("سياسة الاسترجاع", "الاسترجاع خلال 14 يوم.")
    ]
    assert exact["truncated"] is False
    assert "ranking" not in exact  # Exact topics never enter semantic retrieval.
    assert "deposit_policy" not in exact
    assert check_grounding("الاسترجاع خلال 14 يوم", _facts(exact)) is None
    assert check_grounding("الاسترجاع خلال 30 يوم", _facts(exact)) is not None


@pytest.mark.parametrize(
    "topic", ["exchange", "return", "shipping", "hours", "ordering", "cancellation", "deposit"]
)
async def test_missing_topic_never_falls_back_to_unrelated_or_hidden_text(
    db, tenant_ctx, unavailable_embeddings, topic
):
    tenant_id = tenant_ctx.tenant_id
    db.add_all(
        [
            KnowledgeItem(
                tenant_id=tenant_id,
                title="Unrelated policy",
                content="Window is 99 days.",
                source_type="policy",
                source_ref="unrelated",
            ),
            KnowledgeItem(
                tenant_id=tenant_id,
                title="Not a published policy",
                content="Window is 88 days.",
                source_type="text",
                source_ref=topic,
            ),
            KnowledgeItem(
                tenant_id=tenant_id,
                title="Staff policy",
                content="Window is 77 days.",
                source_type="policy",
                source_ref=topic,
                visibility="staff_only",
            ),
        ]
    )
    await db.flush()
    info = await _info(db, tenant_id, topic=topic, question="Please give me the policy")
    assert info["items"] == [] and info["truncated"] is False
    # The note is read by the model: it must both state the fact and forbid inventing.
    assert "متخترعش" in info["note"]
    assert "ranking" not in info
    assert _facts(info) == []
    if topic == "deposit":
        assert info["deposit_policy"] is None


@pytest.mark.parametrize("blank", ["", " \n\t\r "])
async def test_blank_exact_policy_is_not_published_evidence(db, tenant_ctx, blank):
    db.add(
        KnowledgeItem(
            tenant_id=tenant_ctx.tenant_id,
            title="Return policy",
            content=blank,
            source_type="policy",
            source_ref="return",
        )
    )
    await db.flush()
    info = await _info(db, tenant_ctx.tenant_id, topic="return")
    assert info["items"] == []
    assert "note" in info
    assert _facts(info) == []


@pytest.mark.parametrize(("count", "size"), [(31, 1), (5, 1490), (1, 7000)])
async def test_exact_policy_output_keeps_row_and_character_bounds(db, tenant_ctx, count, size):
    db.add_all(
        KnowledgeItem(
            tenant_id=tenant_ctx.tenant_id,
            title="Return policy",
            content="x" * size,
            source_type="policy",
            source_ref="return",
        )
        for _ in range(count)
    )
    await db.flush()
    info = await _info(db, tenant_ctx.tenant_id, topic="return")
    assert len(info["items"]) <= 30
    assert sum(len(i["title"]) + len(i["content"]) for i in info["items"]) <= 6000
    assert info["truncated"] is True


@pytest.mark.parametrize(
    "kwargs", [{}, {"topic": "all"}, {"topic": "deposit", "question": "deposit?"}]
)
async def test_active_deposit_rule_exposes_only_exact_public_facts(
    db, tenant_ctx, unavailable_embeddings, kwargs
):
    tenant_id = tenant_ctx.tenant_id
    await DepositService.save_policy(
        db, tenant_id, name="Superseded 91827", deposit_type="fixed", deposit_value="913"
    )
    await DepositService.save_policy(
        db,
        tenant_id,
        name="Internal campaign 84726",
        deposit_type="percentage",
        deposit_value="20",
        calculation_base="items_after_discounts",
        minimum_deposit="50",
        maximum_deposit="200",
    )
    info = await _info(db, tenant_id, **kwargs)
    assert info["deposit_policy"] == {
        "deposit_type": "percentage",
        "deposit_value": "20.00",
        "currency": "EGP",
        "calculation_base": "items_after_discounts",
        "minimum_deposit": "50.00",
        "maximum_deposit": "200.00",
    }
    assert info["items"] == [] and info["truncated"] is False
    assert "note" not in info  # Empty prose does not mean no published deposit rule.
    assert "ranking" not in info
    facts = _facts(info)
    assert check_grounding("النسبة 20% بحد أدنى 50 وحد أقصى 200", facts) is None
    for number in ("913", "91827", "84726", "1", "2", "100", "180"):
        assert check_grounding(f"العربون {number}", facts) is not None
    assert "Internal campaign 84726" not in facts
    assert set(info) == {"items", "truncated", "deposit_policy"}


@pytest.mark.parametrize("topic", ["all", "deposit"])
async def test_unpublished_deposit_is_null_but_explicit_none_is_a_rule(db, tenant_ctx, topic):
    tenant_id = tenant_ctx.tenant_id
    missing = await _info(db, tenant_id, topic=topic)
    assert missing["deposit_policy"] is None
    assert _facts(missing) == []
    assert check_grounding("العربون 0", _facts(missing)) is not None

    await DepositService.save_policy(
        db, tenant_id, name="No deposit", deposit_type="none", deposit_value="0"
    )
    explicit = await _info(db, tenant_id, topic=topic)
    assert explicit["deposit_policy"] == {
        "deposit_type": "none",
        "deposit_value": "0.00",
        "currency": "EGP",
        "calculation_base": "grand_total",
        "minimum_deposit": None,
        "maximum_deposit": None,
    }
    assert "note" not in explicit
    assert check_grounding("لا نطلب عربون، قيمته 0", _facts(explicit)) is None


async def test_only_inactive_deposit_rules_are_not_published(db, tenant_ctx):
    policy = await DepositService.save_policy(
        db, tenant_ctx.tenant_id, name="Old", deposit_type="fixed", deposit_value="913"
    )
    policy.is_active = False
    await db.flush()
    info = await _info(db, tenant_ctx.tenant_id, topic="deposit")
    assert info["deposit_policy"] is None
    assert _facts(info) == []


async def test_policy_and_deposit_reads_are_tenant_isolated(db, tenant_ctx, unavailable_embeddings):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "return", "الاسترجاع خلال 14 يوم.")
    await DepositService.save_policy(
        db, tenant_id, name="First tenant", deposit_type="fixed", deposit_value="125"
    )
    other = Tenant(slug=f"commerce-{uuid.uuid4().hex[:10]}", name="Other", currency="USD")
    db.add(other)
    await db.flush()
    other_id = other.id
    await bind_tenant(db, other_id)
    assert (await _info(db, other_id, topic="return"))["items"] == []
    assert (await _info(db, other_id, topic="deposit"))["deposit_policy"] is None
    await policies.save_policy(db, other_id, "return", "الاسترجاع خلال 9 أيام.")
    await DepositService.save_policy(
        db, other_id, name="Other tenant", deposit_type="fixed", deposit_value="777"
    )
    other_info = await _info(db, other_id, topic="deposit")
    assert other_info["deposit_policy"]["deposit_value"] == "777.00"
    assert other_info["deposit_policy"]["currency"] == "USD"

    # Mismatched bound/requested tenants prove the application predicate and RLS
    # independently: neither layer may return the other's visible rows.
    mismatch = await _info(db, tenant_id, topic="deposit")
    assert mismatch["deposit_policy"] is None
    assert (await _info(db, tenant_id, topic="return"))["items"] == []
    await bind_tenant(db, tenant_id)
    own = await _info(db, tenant_id)
    assert own["deposit_policy"]["deposit_value"] == "125.00"
    assert own["deposit_policy"]["currency"] == "EGP"
    assert [i["content"] for i in own["items"]] == ["الاسترجاع خلال 14 يوم."]
    assert check_grounding("العربون 777", _facts(own)) is not None


async def test_all_topic_retains_unavailable_ranking_and_structured_deposit(
    db, tenant_ctx, unavailable_embeddings
):
    tenant_id = tenant_ctx.tenant_id
    await policies.save_policy(db, tenant_id, "shipping", "الشحن خلال 3 أيام.")
    await DepositService.save_policy(
        db, tenant_id, name="Fixed", deposit_type="fixed", deposit_value="75.50"
    )
    info = await _info(db, tenant_id, topic="all", question="shipping and deposit?")
    assert info["ranking"] == "unavailable"
    assert [i["content"] for i in info["items"]] == ["الشحن خلال 3 أيام."]
    assert info["deposit_policy"]["deposit_value"] == "75.50"
    assert check_grounding("العربون 75.50", _facts(info)) is None
