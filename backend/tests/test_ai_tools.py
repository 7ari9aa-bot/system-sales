"""AI tool-surface tests (audit N-07, rewritten for the language-only scope).

Two layers:

* DB-free guards pin the CONTRACT of the registry — which tools exist, their
  honest risk levels, and that the escalation tool lets the model choose
  neither the customer nor the conversation (§132 scope binding).
* DB-backed tests prove the handlers actually read the bound tenant's rows
  and compute availability from real balances. They skip when no database
  URL is configured; CI runs them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, ValidationError
from app.modules.ai.models import AIHandover
from app.modules.ai.tools import ToolSpec, get_tool, requires_approval, tool_to_openai_schema
from app.modules.catalog.models import Product, ProductVariant
from app.modules.conversations.models import Conversation
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer

# The language-only tool surface (scope cut, 2026-10-18).
NEW_TOOLS = (
    "search_catalog",
    "get_product_details",
    "get_product_photos",
    "find_product_by_image",
    "get_store_info",
    "get_my_orders",
    "search_knowledge",
    "handover_to_human",
)

REMOVED_TOOLS = (
    "search_products",
    "get_variant_price",
    "check_stock",
    "get_customer",
    "get_order",
    "add_task",
    "add_tag",
    "create_order",
    "resolve_product_media",
)


# ------------------------------------------------------- registry contract --


def test_language_only_tools_are_registered() -> None:
    for name in NEW_TOOLS:
        spec = get_tool(name)
        assert spec is not None, f"{name} is not registered"
        assert spec.name == name
        assert spec.description
        assert spec.args_schema is not None
        assert spec.handler is not None


def test_order_tools_are_gone() -> None:
    """The scope cut is a deletion, not an authorization tweak: nothing named
    like the old sales surface may remain registered."""
    for name in REMOVED_TOOLS:
        assert get_tool(name) is None, f"{name} is still registered"


@pytest.mark.parametrize(
    ("name", "risk"),
    [
        ("search_catalog", "LOW"),
        ("get_product_details", "LOW"),
        ("get_product_photos", "LOW"),
        ("find_product_by_image", "LOW"),
        ("get_store_info", "LOW"),
        ("get_my_orders", "LOW"),
        ("search_knowledge", "LOW"),
        ("handover_to_human", "MEDIUM"),
    ],
)
def test_risk_levels_are_honest(name: str, risk: str) -> None:
    """Reads are LOW; the handover write is MEDIUM; nothing is HIGH."""
    assert get_tool(name).risk_level == risk


async def test_only_high_risk_tools_require_approval() -> None:
    from pydantic import BaseModel

    class _Empty(BaseModel):
        pass

    for name in NEW_TOOLS:
        assert await requires_approval(get_tool(name)) is False

    # The gate itself stays generic: a future HIGH tool parks by level.
    fake = ToolSpec(
        name="future_high_tool",
        description="",
        args_schema=_Empty,
        handler=None,  # type: ignore[arg-type]
        risk_level="HIGH",
    )
    assert await requires_approval(fake, {}) is True


def test_escalation_tool_never_lets_the_model_choose_the_scope() -> None:
    """§132: the conversation is bound server-side — the schema omits it, and
    even a model that sends one anyway has it dropped before the handler."""
    spec = get_tool("handover_to_human")
    properties = tool_to_openai_schema(spec)["function"]["parameters"]["properties"]
    assert set(properties) == {"reason", "summary"}
    dumped = spec.args_schema(
        reason="missing_data",
        summary="لا توجد سياسة استرجاع مسجلة",
        **{"conversation_id": str(uuid.uuid4()), "customer_id": str(uuid.uuid4())},
    ).model_dump()
    assert "conversation_id" not in dumped
    assert "customer_id" not in dumped


def test_get_store_info_has_one_optional_question() -> None:
    """The model never chooses between "the list" and "a search": one tool, and
    the question only reorders. It must stay optional so the plain pull works."""
    spec = get_tool("get_store_info")
    parameters = tool_to_openai_schema(spec)["function"]["parameters"]
    assert set(parameters["properties"]) == {"question"}
    assert "question" not in (parameters.get("required") or [])


def test_search_knowledge_cannot_ask_for_hidden_visibility() -> None:
    """§157: retrieval visibility is a server decision, not a model argument."""
    spec = get_tool("search_knowledge")
    properties = tool_to_openai_schema(spec)["function"]["parameters"]["properties"]
    assert "query" in properties
    assert "visibility" not in properties


def test_every_customer_tool_rejects_an_undeclared_argument() -> None:
    """A handler only ever receives what its schema declares. `visibility` or an
    id the tool never asked for is an error, and the schema the model is shown
    says so (`additionalProperties: false`) without relying on a provider's
    `strict` mode, which a per-tenant OpenAI-compatible endpoint may not have."""
    from pydantic import ValidationError as PydanticValidationError

    minimal = {
        "search_catalog": {"query": "x"},
        "get_product_details": {"product_id": str(uuid.uuid4())},
        "get_product_photos": {"product_id": str(uuid.uuid4())},
        "find_product_by_image": {"image_kind": "product"},
        "get_store_info": {},
        "get_my_orders": {},
        "search_knowledge": {"query": "x"},
        "handover_to_human": {"reason": "complaint", "summary": "s"},
    }
    assert set(minimal) == set(NEW_TOOLS)  # every tool is accounted for
    # The escalation tool is the deliberate exception: it DROPS an extra
    # conversation_id/customer_id rather than failing the handover (see
    # test_escalation_tool_never_lets_the_model_choose_the_scope).
    minimal.pop("handover_to_human")
    for name, valid in minimal.items():
        spec = get_tool(name)
        spec.args_schema(**valid)  # the minimal call itself is fine
        with pytest.raises(PydanticValidationError):
            spec.args_schema(**valid, visibility="staff_only")
        schema = tool_to_openai_schema(spec)["function"]["parameters"]
        assert schema.get("additionalProperties") is False, name


async def test_search_knowledge_requests_customer_facing_visibility(monkeypatch) -> None:
    """The RAG tool reuses the knowledge service AND keeps §157 scoping.

    The fake mirrors the REAL signature (default ``visibility="customer_facing"``)
    and applies the same filter the service applies. The handler must request
    customer_facing explicitly — a security boundary must not ride on another
    module's default. If it asked for ``visibility="staff_only"`` (a data-leak
    regression) the staff-only hit would come back and both assertions below
    would fail.
    """
    from app.modules.ai import knowledge

    calls: list[dict] = []

    class _Item:
        def __init__(self, title: str, content: str, visibility: str) -> None:
            self.title = title
            self.content = content
            self.source_type = "text"
            self.visibility = visibility

    public = _Item("Shipping", "Orders ship in 2 days.", "customer_facing")
    internal = _Item("Margins", "We pay 12 EGP per unit.", "staff_only")

    async def _fake_search(session, tenant_id, query, *, limit=5, visibility="customer_facing"):
        calls.append(
            {"tenant_id": tenant_id, "query": query, "limit": limit, "visibility": visibility}
        )
        rows = [(public, 0.1), (internal, 0.2)]
        if visibility is not None:
            rows = [(item, d) for item, d in rows if item.visibility == visibility]
        return rows[:limit]

    monkeypatch.setattr(knowledge, "search_knowledge", _fake_search)

    tenant_id = uuid.uuid4()
    spec = get_tool("search_knowledge")
    kwargs = spec.args_schema(query="how long is shipping", limit=3).model_dump()
    result = await spec.handler(None, tenant_id, **kwargs)

    assert calls == [
        {
            "tenant_id": tenant_id,
            "query": "how long is shipping",
            "limit": 3,
            "visibility": "customer_facing",
        }
    ]
    assert result["results"] == [
        {"title": "Shipping", "content": "Orders ship in 2 days.", "source_type": "text"}
    ]
    assert [r["title"] for r in result["results"]] == ["Shipping"]


async def test_search_knowledge_surfaces_a_misconfigured_embedding_model(
    monkeypatch,
) -> None:
    """A broken RAG setup must be VISIBLE, not an empty result set.

    Swallowing this made "no embedding model" indistinguishable from "nothing
    matched", so the model told the customer "I don't know". It must instead
    fail loudly — the runtime records the failed call and the model receives
    an explicit error.
    """
    from app.modules.ai import knowledge

    async def _no_model(session, tenant_id, query, *, limit=5, visibility="customer_facing"):
        raise ValidationError("no model configured for alias embedding")

    monkeypatch.setattr(knowledge, "search_knowledge", _no_model)

    spec = get_tool("search_knowledge")
    with pytest.raises(DomainError, match="knowledge search unavailable"):
        await spec.handler(None, uuid.uuid4(), query="anything")


async def test_malformed_binding_is_a_controlled_tool_error() -> None:
    """A corrupt context id must be a DomainError, not a raw ValueError.

    No session is needed: the binding is parsed before any query runs.
    """
    bad = {"conversation_id": "not-a-uuid"}
    with pytest.raises(DomainError):
        await get_tool("handover_to_human").handler(
            None,
            uuid.uuid4(),
            reason="customer_request",
            summary="طلب موظف",
            context=bad,
        )


# ------------------------------------------------------------ DB-backed -----


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    from app.modules.inventory.models import Warehouse

    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="WH",
        code=f"W-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse.id


async def _conversation(db: AsyncSession, tenant_id: uuid.UUID):
    customer = Customer(tenant_id=tenant_id, name="Tool Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await db.flush()
    return customer, conversation


async def _variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str = "Widget",
    status: str = "active",
) -> ProductVariant:
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"w-{uuid.uuid4().hex[:8]}",
        status=status,
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"W-{uuid.uuid4().hex[:6].upper()}",
        title=f"{title} M",
        price=Decimal("25.50"),
    )
    db.add(variant)
    await db.flush()
    return variant


async def test_search_catalog_returns_price_and_availability(db, tenant_ctx) -> None:
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=await _warehouse(db, tenant_id),
            variant_id=variant.id,
            on_hand=10,
            reserved=2,
        )
    )
    await db.flush()

    spec = get_tool("search_catalog")
    kwargs = spec.args_schema(query="Widget").model_dump()
    result = await spec.handler(db, tenant_id, **kwargs)

    assert len(result["results"]) == 1
    assert result["total_matches"] == 1
    row = result["results"][0]
    assert row["price"] == "25.50"
    assert row["availability"]["status"] == "متوفر"


async def test_search_catalog_counts_only_the_shelf_the_cashier_sells_from(
    db, tenant_ctx
) -> None:
    """A back-store warehouse must not make the agent say "متوفر" for goods the till lacks."""
    from app.modules.inventory.models import InventoryBalance
    from app.modules.pos.profiles import PosProfileService

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    shop = await _warehouse(db, tenant_id)
    back_store = await _warehouse(db, tenant_id)
    db.add_all(
        [
            InventoryBalance(
                tenant_id=tenant_id, warehouse_id=shop, variant_id=variant.id, on_hand=0, reserved=0
            ),
            InventoryBalance(
                tenant_id=tenant_id,
                warehouse_id=back_store,
                variant_id=variant.id,
                on_hand=40,
                reserved=0,
            ),
        ]
    )
    await PosProfileService.create(db, tenant_id, name="Main", code="MAIN", warehouse_id=shop)
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, **spec.args_schema(query="Widget").model_dump())

    assert result["results"][0]["availability"]["status"] == "خلص"


async def test_search_catalog_sums_every_warehouse_when_no_till_exists(db, tenant_ctx) -> None:
    """A shop that has not set up a cashier yet keeps the all-warehouses behaviour."""
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    for qty in (3, 4):
        db.add(
            InventoryBalance(
                tenant_id=tenant_id,
                warehouse_id=await _warehouse(db, tenant_id),
                variant_id=variant.id,
                on_hand=qty,
                reserved=0,
            )
        )
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, **spec.args_schema(query="Widget").model_dump())

    assert result["results"][0]["availability"]["status"] == "متوفر"  # 3 + 4 = 7 > 5


async def test_agent_quotes_the_same_unit_price_as_the_cashier(db, tenant_ctx) -> None:
    """The price ladder the till uses for qty 1 is the price the agent quotes."""
    from app.core.tenancy import resolve_tenant_currency
    from app.modules.catalog.models import ProductPrice

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)  # base price 25.50
    currency = await resolve_tenant_currency(db, tenant_id)
    db.add(
        ProductPrice(
            tenant_id=tenant_id,
            variant_id=variant.id,
            currency=currency,
            unit_price=Decimal("19.00"),
            min_quantity=1,
        )
    )
    await db.flush()

    search = get_tool("search_catalog")
    found = await search.handler(db, tenant_id, **search.args_schema(query="Widget").model_dump())
    details = get_tool("get_product_details")
    detail = await details.handler(db, tenant_id, product_id=variant.product_id)

    assert found["results"][0]["price"] == "19.00"
    assert detail["variants"][0]["price"] == "19.00"


async def test_search_catalog_reports_restock_when_empty(db, tenant_ctx) -> None:
    from datetime import date

    from app.modules.ai.models import IncomingStock
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=await _warehouse(db, tenant_id),
            variant_id=variant.id,
            on_hand=0,
            reserved=0,
        )
    )
    db.add(
        IncomingStock(
            tenant_id=tenant_id,
            variant_id=variant.id,
            expected_on=date(2026, 10, 25),
            confidence="confirmed",
        )
    )
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="Widget")
    row = result["results"][0]
    assert row["availability"]["status"] == "هيتجدد"
    # The ready label carries certainty and WESTERN digits — grounding matches
    # facts verbatim, and an Arabic-Indic label would never ground "25".
    assert row["availability"]["restock_label"] == "مؤكد: 25 أكتوبر 2026"
    # The raw day-count is a fact too: "بعد 6 أيام" is quotable, "حسبتها" is not.
    assert row["availability"]["restock_in_days"] == (
        date(2026, 10, 25) - date.today()
    ).days


async def test_search_catalog_hides_restock_from_an_in_stock_variant(db, tenant_ctx) -> None:
    """The restock promise only matters when the shelf is empty — an open
    incoming row must not ride an AVAILABLE variant, or the model will offer
    a future shipment for something the customer can buy today."""
    from datetime import date

    from app.modules.ai.models import IncomingStock
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=await _warehouse(db, tenant_id),
            variant_id=variant.id,
            on_hand=50,
            reserved=0,
        )
    )
    db.add(
        IncomingStock(
            tenant_id=tenant_id,
            variant_id=variant.id,
            expected_on=date(2026, 10, 25),
            confidence="confirmed",
        )
    )
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="Widget")
    row = result["results"][0]
    assert row["availability"]["status"] == "متوفر"
    assert row["availability"]["restock_label"] is None


async def test_search_catalog_reports_sold_out_without_restock(db, tenant_ctx) -> None:
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=await _warehouse(db, tenant_id),
            variant_id=variant.id,
            on_hand=0,
            reserved=0,
        )
    )
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="Widget")
    row = result["results"][0]
    assert row["availability"]["status"] == "خلص"
    assert row["availability"]["restock_label"] is None


async def test_search_catalog_marks_the_low_band(db, tenant_ctx) -> None:
    from app.modules.inventory.models import InventoryBalance

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=await _warehouse(db, tenant_id),
            variant_id=variant.id,
            on_hand=3,
            reserved=0,
        )
    )
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="Widget")
    assert result["results"][0]["availability"]["status"] == "قليل"


async def test_search_catalog_hides_nonsellable_products_from_results(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _variant(db, tenant_id, status="draft")

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="Widget")
    assert result["results"] == []


async def test_get_product_details_returns_every_variant(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    product = Product(
        tenant_id=tenant_id,
        title="قميص",
        slug=f"s-{uuid.uuid4().hex[:8]}",
        status="active",
        attributes={"material": "قطن"},
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"S-{uuid.uuid4().hex[:6].upper()}",
        title="قميص M",
        price=Decimal("100.00"),
        option_values={"size": "M"},
    )
    db.add(variant)
    await db.flush()

    spec = get_tool("get_product_details")
    result = await spec.handler(db, tenant_id, product_id=product.id)
    assert result["title"] == "قميص"
    assert result["attributes"] == {"material": "قطن"}
    assert [v["variant_id"] for v in result["variants"]] == [str(variant.id)]
    assert result["variants"][0]["option_values"] == {"size": "M"}


async def test_get_product_details_refuses_another_tenant(db, tenant_ctx) -> None:
    from app.core.errors import NotFoundError

    tenant_id = tenant_ctx.tenant_id
    variant = await _variant(db, tenant_id)
    product_id = variant.product_id

    spec = get_tool("get_product_details")
    with pytest.raises(NotFoundError):
        await spec.handler(db, uuid.uuid4(), product_id=product_id)


async def test_get_store_info_stops_at_the_token_budget(db, tenant_ctx) -> None:
    """Merchant content is unbounded Text: the pull stops at the budget
    instead of flooding the model's context with one prolific store."""
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    for i in range(40):
        db.add(
            KnowledgeItem(
                tenant_id=tenant_id,
                title=f"بند {i}",
                source_type="text",
                content="ا" * 500,
                visibility="customer_facing",
            )
        )
    await db.flush()

    spec = get_tool("get_store_info")
    result = await spec.handler(db, tenant_id)
    total = sum(len(i["title"]) + len(i["content"]) for i in result["items"])
    assert len(result["items"]) < 40
    assert total <= 6000


async def test_get_store_info_reads_customer_facing_items_only(db, tenant_ctx) -> None:
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    db.add(
        KnowledgeItem(
            tenant_id=tenant_id,
            title="مواعيد العمل",
            source_type="text",
            content="من 10 الصبح لـ 10 بالليل.",
            visibility="customer_facing",
        )
    )
    db.add(
        KnowledgeItem(
            tenant_id=tenant_id,
            title="هامش الربح",
            source_type="text",
            content="سري.",
            visibility="staff_only",
        )
    )
    await db.flush()

    spec = get_tool("get_store_info")
    result = await spec.handler(db, tenant_id)
    titles = [item["title"] for item in result["items"]]
    assert "مواعيد العمل" in titles
    assert "هامش الربح" not in titles


async def test_get_store_info_says_how_old_each_item_is(db, tenant_ctx) -> None:
    """The model cannot hedge a stale hours/policy answer if it cannot see
    its age. ISO + a `*_at` key: the fact ledger skips it, so the timestamp is
    visible to the model without becoming a numeral it may quote."""
    from app.modules.ai.agents.customer.ledger import facts_from_tool_calls
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    db.add(
        KnowledgeItem(
            tenant_id=tenant_id,
            title="مواعيد العمل",
            source_type="text",
            content="من الصبح لبالليل.",
            visibility="customer_facing",
        )
    )
    await db.flush()

    result = await get_tool("get_store_info").handler(db, tenant_id)
    updated_at = result["items"][0]["updated_at"]
    assert updated_at and "T" in updated_at
    facts = facts_from_tool_calls([{"status": "ok", "result": result}])
    assert updated_at not in facts
    assert not any(updated_at[:10] in f for f in facts)


async def test_get_store_info_reports_when_the_list_is_not_the_whole_store(
    db, tenant_ctx
) -> None:
    """Silence about a policy must not read as "the store has none": a cut-off
    pull says so, whether the item cap or the token budget did the cutting."""
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    for i in range(40):
        db.add(
            KnowledgeItem(
                tenant_id=tenant_id,
                title=f"بند {i}",
                source_type="text",
                content="ا" * 500,
                visibility="customer_facing",
            )
        )
    await db.flush()
    result = await get_tool("get_store_info").handler(db, tenant_id)
    assert result["truncated"] is True


async def test_get_store_info_is_not_truncated_when_everything_fits(db, tenant_ctx) -> None:
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    for i in range(3):
        db.add(
            KnowledgeItem(
                tenant_id=tenant_id,
                title=f"بند {i}",
                source_type="text",
                content="قصير",
                visibility="customer_facing",
            )
        )
    await db.flush()
    result = await get_tool("get_store_info").handler(db, tenant_id)
    assert len(result["items"]) == 3
    assert result["truncated"] is False


async def _knowledge(db, tenant_id, titles, *, content="قصير"):
    from app.modules.ai.models import KnowledgeItem

    items = []
    for title in titles:
        item = KnowledgeItem(
            tenant_id=tenant_id,
            title=title,
            source_type="text",
            content=content,
            visibility="customer_facing",
        )
        db.add(item)
        items.append(item)
    await db.flush()
    return items


async def test_get_store_info_ranks_by_the_question_when_retrieval_works(
    db, tenant_ctx, monkeypatch
) -> None:
    """The relevant item is the LAST one by age and the budget would cut it:
    ranking has to happen before the cut, or the question changes nothing."""
    from app.modules.ai import knowledge

    tenant_id = tenant_ctx.tenant_id
    filler = await _knowledge(db, tenant_id, [f"بند {i}" for i in range(35)], content="ا" * 400)
    target = (await _knowledge(db, tenant_id, ["سياسة الاسترجاع"]))[0]

    async def _search(session, tid, query, *, limit=5, visibility="customer_facing"):
        return [(target, 0.1)]

    monkeypatch.setattr(knowledge, "search_knowledge", _search)

    spec = get_tool("get_store_info")
    plain = await spec.handler(db, tenant_id)
    ranked = await spec.handler(db, tenant_id, question="ينفع ارجع؟")

    assert "سياسة الاسترجاع" not in [i["title"] for i in plain["items"]]
    assert ranked["items"][0]["title"] == "سياسة الاسترجاع"
    assert ranked["ranking"] == "by_relevance"
    assert "ranking" not in plain
    assert len(filler) == 35


async def test_get_store_info_still_answers_when_retrieval_is_down(
    db, tenant_ctx, monkeypatch
) -> None:
    """Hours and returns must not depend on an embedding vendor, and the outage
    must not be swallowed either: the items come back AND the result says the
    ranking was unavailable."""
    from app.modules.ai import knowledge

    tenant_id = tenant_ctx.tenant_id
    await _knowledge(db, tenant_id, ["مواعيد العمل"])

    async def _no_model(session, tid, query, *, limit=5, visibility="customer_facing"):
        raise ValidationError("no model configured for alias embedding")

    monkeypatch.setattr(knowledge, "search_knowledge", _no_model)

    result = await get_tool("get_store_info").handler(db, tenant_id, question="بتفتحوا امتى")
    assert [i["title"] for i in result["items"]] == ["مواعيد العمل"]
    assert result["ranking"] == "unavailable"


async def test_get_store_info_without_a_question_never_touches_retrieval(
    db, tenant_ctx, monkeypatch
) -> None:
    from app.modules.ai import knowledge

    tenant_id = tenant_ctx.tenant_id
    await _knowledge(db, tenant_id, ["مواعيد العمل"])

    async def _boom(*args, **kwargs):
        raise AssertionError("retrieval must not run without a question")

    monkeypatch.setattr(knowledge, "search_knowledge", _boom)

    result = await get_tool("get_store_info").handler(db, tenant_id)
    assert [i["title"] for i in result["items"]] == ["مواعيد العمل"]
    assert result["truncated"] is False


async def test_get_store_info_ranked_items_never_leak_hidden_visibility(
    db, tenant_ctx, monkeypatch
) -> None:
    """Even if retrieval returned a staff-only item id, the pull re-applies the
    customer_facing filter — ranking reorders, it never widens."""
    from app.modules.ai import knowledge
    from app.modules.ai.models import KnowledgeItem

    tenant_id = tenant_ctx.tenant_id
    secret = KnowledgeItem(
        tenant_id=tenant_id,
        title="هامش الربح",
        source_type="text",
        content="سري.",
        visibility="staff_only",
    )
    db.add(secret)
    await db.flush()

    async def _search(session, tid, query, *, limit=5, visibility="customer_facing"):
        return [(secret, 0.0)]

    monkeypatch.setattr(knowledge, "search_knowledge", _search)
    result = await get_tool("get_store_info").handler(db, tenant_id, question="الربح")
    assert "هامش الربح" not in [i["title"] for i in result["items"]]


async def test_handover_to_human_writes_the_handover(db, tenant_ctx) -> None:
    """The model's escalation decision becomes the ONE durable handover:
    the row, the conversation status, and the summary the staff reads."""
    tenant_id = tenant_ctx.tenant_id
    _customer, conversation = await _conversation(db, tenant_id)

    spec = get_tool("handover_to_human")
    result = await spec.handler(
        db,
        tenant_id,
        reason="missing_data",
        summary="حاولت أجاوب على سياسة الاسترجاع ومفيش سياسة مسجلة",
        context={"conversation_id": str(conversation.id)},
    )
    assert result["status"] == "handover_recorded"

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "missing_data"
    assert handover.status == "pending"
    assert "سياسة الاسترجاع" in (handover.note or "")

    refreshed_status = (
        await db.execute(
            select(Conversation.status).where(Conversation.id == conversation.id)
        )
    ).scalar_one()
    assert refreshed_status == "waiting_human"


async def test_handover_to_human_is_idempotent_per_conversation(db, tenant_ctx) -> None:
    """A model that calls the tool twice converges on ONE open handover."""
    tenant_id = tenant_ctx.tenant_id
    _customer, conversation = await _conversation(db, tenant_id)

    spec = get_tool("handover_to_human")
    await spec.handler(
        db,
        tenant_id,
        reason="complex_problem",
        summary="الأول",
        context={"conversation_id": str(conversation.id)},
    )
    await spec.handler(
        db,
        tenant_id,
        reason="complex_problem",
        summary="التاني",
        context={"conversation_id": str(conversation.id)},
    )

    rows = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


# --------------------------------------------- LIKE escaping (A7, DB-free) --


class _CapturingSession:
    """Records the statement ``_search_catalog`` builds; returns no rows.

    DB-free: the handler only calls ``.all()`` on the result, so nothing here
    touches a database. The captured statement compiles offline, which is what
    lets a local run assert the bound LIKE pattern's shape.
    """

    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement, params=None):  # noqa: ANN001, ARG002
        self.statement = statement
        return _NoRows()


class _NoRows:
    def all(self) -> list:
        return []

    def scalars(self):
        return self._rows

    def scalar_one(self) -> int:
        return 0

    def first(self):  # noqa: ANN201
        return None


def _search_patterns(query: str) -> tuple[str, list[str]]:
    """Compile ``_search_catalog``'s SELECT for ``query`` offline.

    Returns (rendered SQL, every string bound param) so a test can assert the
    LIKE pattern reaches the driver escaped, and that the statement declares an
    ESCAPE clause (without it a backslash is literal text, not an escape).
    """
    import asyncio

    from sqlalchemy.dialects import postgresql

    from app.modules.ai.tools import _search_catalog

    session = _CapturingSession()
    asyncio.run(_search_catalog(session, uuid.uuid4(), query=query, limit=5))
    compiled = session.statement.compile(dialect=postgresql.dialect())
    params = [v for v in compiled.params.values() if isinstance(v, str)]
    return str(compiled), params


@pytest.mark.parametrize(
    ("query", "expected_core"),
    [
        ("widget", "widget"),  # no metacharacter: passes through verbatim
        ("100%", r"100\%"),  # '%' widened a LIKE to match-everything
        ("a_b", r"a\_b"),  # '_' matched any single character
        (r"back\slash", r"back\\slash"),  # the escape char itself must double
        ("%_%", r"\%\_\%"),
    ],
)
def test_search_catalog_escapes_like_wildcards(query: str, expected_core: str) -> None:
    """A7: a search term must narrow, never widen — escape LIKE metacharacters.

    The handler wraps the (escaped) term in the wildcards IT chooses, so a
    caller-supplied '%' cannot turn "search for one thing" into "dump the whole
    catalog", and a '%' or '_' is matched literally.
    """
    sql, params = _search_patterns(query)
    assert "ESCAPE" in sql.upper(), f"no ESCAPE clause, backslash is literal:\n{sql}"

    expected_pattern = f"%{expected_core}%"
    assert expected_pattern in params, (
        f"expected escaped pattern {expected_pattern!r}, got {params!r}"
    )
    # The unescaped pattern is the vulnerability: it must never be bound.
    if expected_pattern != f"%{query}%":
        assert f"%{query}%" not in params, f"raw wildcard leaked into {params!r}"


def test_search_catalog_percent_query_does_not_match_everything() -> None:
    """The concrete A7 attack: query='%' must not become a match-all pattern.

    Unescaped, the pattern was '%%%' (matches every row). Escaped, it is
    '%\\%%' — rows whose title/sku literally contain a percent sign.
    """
    _, params = _search_patterns("%")
    assert "%%%" not in params, f"match-all pattern bound: {params!r}"
    assert r"%\%%" in params, params


# ------------------------------- structured spec search (P1, DB-free) -------


def _search_sql(**kwargs: object) -> str:
    """Compile ``_search_catalog``'s SELECT for the given arguments, offline."""
    import asyncio

    from sqlalchemy.dialects import postgresql

    from app.modules.ai.tools import _search_catalog

    session = _CapturingSession()
    asyncio.run(_search_catalog(session, uuid.uuid4(), **kwargs))
    return str(session.statement.compile(dialect=postgresql.dialect()))


def test_search_catalog_uses_the_indexed_full_text_arm() -> None:
    """`products.search_ts` is a generated tsvector with a GIN index (§45).

    Before this, a multi-word query was a LIKE scan over the title only, so a
    word in the DESCRIPTION could never match and the index went unused.
    """
    sql = _search_sql(query="قميص قطن", limit=5)
    assert "plainto_tsquery" in sql.lower()
    assert "@@" in sql
    # The substring arms stay: a substring INSIDE a word ("قطن" in "قطني") is
    # trigram work, not tsvector — the column's own note.
    assert "ILIKE" in sql.upper()


def test_search_catalog_matches_any_word_not_the_whole_phrase() -> None:
    """The phrase killer: a four-word ask with AND semantics matched nothing
    when any word was absent. Each word gets its own tsquery arm — one
    matching word surfaces the product, and total_matches tells the model
    whether to show options or ask."""
    two_words = _search_sql(query="تيشرت أسود", limit=5)
    single = _search_sql(query="تيشرت", limit=5)
    # each arm renders the function name twice; the ratio is what matters
    assert two_words.count("plainto_tsquery") == 2 * single.count("plainto_tsquery"), (
        "words are ANDed, not ORed"
    )


def test_search_catalog_strips_the_article_and_matches_past_the_hamza() -> None:
    """Customers write ال and type hamza loosely; catalogs don't. The tail
    arm (first two characters dropped) matches both: "الأسود" carries "أسود"
    as its tail, and "احمر"'s tail "حمر" sits inside "أحمر" either way."""
    import asyncio

    from app.modules.ai.tools import _search_catalog

    class _CapturingMulti:
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, statement, params=None):  # noqa: ANN001, ARG002
            self.statements.append(statement)
            return _NoRows()

    session = _CapturingMulti()
    asyncio.run(_search_catalog(session, uuid.uuid4(), query="الأسود احمر"))
    like_params = [
        v
        for stmt in session.statements
        for v in stmt.compile().params.values()
        if isinstance(v, str) and v.startswith("%")
    ]
    joined = " ".join(like_params)
    assert "%أسود%" in joined, f"the article was not stripped: {like_params!r}"
    assert "%حمر%" in joined, f"the hamza tail arm is missing: {like_params!r}"


def test_search_catalog_reports_zero_matches_with_a_retry_hint() -> None:
    """An empty result carries the retry hint — the model asks or retries,
    it does not invent a product."""
    import asyncio

    from app.modules.ai.tools import _search_catalog

    session = _CapturingSession()
    result = asyncio.run(_search_catalog(session, uuid.uuid4(), query="حاجة مش موجودة"))
    assert result["results"] == []
    assert result["total_matches"] == 0
    assert "مفيش مطابق" in result["hint"]


def test_search_catalog_without_specs_is_still_the_plain_keyword_path() -> None:
    """Optional filters must not change the shape of the default query."""
    sql = _search_sql(query="قميص", limit=5)
    assert "@>" not in sql, "a containment predicate appeared with no specs given"


def test_search_catalog_matches_structured_specs_by_containment() -> None:
    """A spec the customer named is decided by the database, not by a LIKE.

    Color lives in `products.attributes`, size in `product_variants.option_values`
    — neither is in a name the old ILIKE could reach.
    """
    sql = _search_sql(
        query="قميص", attributes={"color": "أحمر"}, option_values={"size": "M"}, limit=5
    )
    assert sql.count("@>") == 2, sql
    assert "products.attributes" in sql
    assert "product_variants.option_values" in sql


def test_search_catalog_keeps_the_sellable_gate() -> None:
    """Browsing must agree with checkout: active variants of sellable products."""
    upper = _search_sql(query="x", limit=5).upper()
    assert "IS_ACTIVE" in upper
    assert "STATUS IN" in upper


def test_the_search_tool_advertises_the_structured_specs() -> None:
    """The model can only pass a filter the tool's schema declares."""
    from app.modules.ai.tools import SearchCatalogArgs

    fields = SearchCatalogArgs.model_fields
    assert "attributes" in fields
    assert "option_values" in fields
    # Optional, so the previous call shape keeps working unchanged.
    args = SearchCatalogArgs(query="x")
    assert args.attributes is None
    assert args.option_values is None


async def test_search_catalog_ranks_word_matches_first(db, tenant_ctx):
    """CI-only: the black-t-shirt ask must not open with chinos that merely
    share the color — rows matching MORE of the customer's words rank first,
    regardless of the alphabet."""
    tenant_id = tenant_ctx.tenant_id
    shirt = Product(
        tenant_id=tenant_id,
        title="تيشيرت أسود",
        slug=f"ts-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    pants = Product(
        tenant_id=tenant_id,
        title="بنطلون أسود",
        slug=f"pn-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add_all([shirt, pants])
    await db.flush()
    shirt_v = ProductVariant(
        tenant_id=tenant_id,
        product_id=shirt.id,
        sku=f"TS-{uuid.uuid4().hex[:6].upper()}",
        title="تيشيرت أسود M",
        price=Decimal("100.00"),
    )
    pants_v = ProductVariant(
        tenant_id=tenant_id,
        product_id=pants.id,
        sku=f"PN-{uuid.uuid4().hex[:6].upper()}",
        title="بنطلون أسود M",
        price=Decimal("150.00"),
    )
    db.add_all([shirt_v, pants_v])
    await db.flush()

    spec = get_tool("search_catalog")
    result = await spec.handler(db, tenant_id, query="تيشيرت اسود", limit=20)
    titles = [row["title"] for row in result["results"]]
    assert "تيشيرت أسود M" in titles
    assert titles[0].startswith("تيشيرت"), f"ranking put {titles!r} first"


async def test_structured_specs_are_matched_by_the_database(db, tenant_ctx):
    """CI-only: needs `DATABASE_URL_APP_ADMIN`, skips locally.

    The behavioural half of the containment filter. Two shirts share the title
    "قميص" and differ only in `attributes.color`; two variants of the red one
    differ only in `option_values.size`. A name-based ILIKE cannot tell any of
    them apart — the JSONB containment is what does.
    """
    tenant_id = tenant_ctx.tenant_id
    red = Product(
        tenant_id=tenant_id,
        title="قميص",
        slug=f"shirt-red-{uuid.uuid4().hex[:8]}",
        status="active",
        attributes={"color": "أحمر", "material": "قطن"},
    )
    blue = Product(
        tenant_id=tenant_id,
        title="قميص",
        slug=f"shirt-blue-{uuid.uuid4().hex[:8]}",
        status="active",
        attributes={"color": "أزرق", "material": "قطن"},
    )
    db.add_all([red, blue])
    await db.flush()

    red_m = ProductVariant(
        tenant_id=tenant_id,
        product_id=red.id,
        sku=f"RM-{uuid.uuid4().hex[:6].upper()}",
        title="قميص M",
        price=Decimal("100.00"),
        option_values={"size": "M"},
    )
    red_l = ProductVariant(
        tenant_id=tenant_id,
        product_id=red.id,
        sku=f"RL-{uuid.uuid4().hex[:6].upper()}",
        title="قميص L",
        price=Decimal("100.00"),
        option_values={"size": "L"},
    )
    blue_m = ProductVariant(
        tenant_id=tenant_id,
        product_id=blue.id,
        sku=f"BM-{uuid.uuid4().hex[:6].upper()}",
        title="قميص M",
        price=Decimal("100.00"),
        option_values={"size": "M"},
    )
    db.add_all([red_m, red_l, blue_m])
    await db.flush()

    spec = get_tool("search_catalog")
    kwargs = spec.args_schema(
        query="قميص", attributes={"color": "أحمر"}, option_values={"size": "M"}, limit=20
    ).model_dump()
    result = await spec.handler(db, tenant_id, **kwargs)

    assert [row["variant_id"] for row in result["results"]] == [str(red_m.id)]


# ------------------------------------------------------ get_my_orders -------


def test_get_my_orders_takes_no_customer_argument() -> None:
    """The customer is server-bound: the model has no way to name another one."""
    fields = set(get_tool("get_my_orders").args_schema.model_fields)
    assert fields == {"number", "limit"}
    with pytest.raises(PydanticValidationError):
        get_tool("get_my_orders").args_schema(customer_id=str(uuid.uuid4()))


async def _checkout_for(db, tenant_id, customer_id, variant, *, qty=1):
    from app.modules.orders.service import OrderService

    return await OrderService.create_order(
        db, tenant_id, customer_id, [{"variant_id": variant.id, "quantity": qty}]
    )


async def _stocked_variant(db, tenant_id):
    from app.modules.inventory.service import InventoryService

    variant = await _variant(db, tenant_id)
    warehouse = await InventoryService.get_default_warehouse(db, tenant_id)
    await InventoryService.move(
        db, tenant_id, variant.id, warehouse.id, direction="in", quantity=20, reason="purchase"
    )
    return variant


async def test_get_my_orders_returns_only_the_bound_customers_invoices(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    variant = await _stocked_variant(db, tenant_id)
    mine, _ = await _conversation(db, tenant_id)
    other, _ = await _conversation(db, tenant_id)
    my_order = await _checkout_for(db, tenant_id, mine.id, variant, qty=2)
    their_order = await _checkout_for(db, tenant_id, other.id, variant)

    spec = get_tool("get_my_orders")
    result = await spec.handler(db, tenant_id, context={"customer_id": str(mine.id)})
    numbers = [row["number"] for row in result["orders"]]
    assert numbers == [my_order.number]
    assert their_order.number not in numbers
    assert result["orders"][0]["items"][0]["quantity"] == 2
    assert result["orders"][0]["returned"] is None

    # Guessing the other customer's invoice number finds nothing, not their data.
    guessed = await spec.handler(
        db, tenant_id, number=their_order.number, context={"customer_id": str(mine.id)}
    )
    assert guessed["orders"] == []
    assert their_order.number not in str(guessed)


async def test_get_my_orders_needs_a_bound_customer(db, tenant_ctx) -> None:
    spec = get_tool("get_my_orders")
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_ctx.tenant_id, context={})
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_ctx.tenant_id)


async def test_get_my_orders_hides_a_deleted_invoice(db, tenant_ctx) -> None:
    from sqlalchemy import text as sql_text

    tenant_id = tenant_ctx.tenant_id
    variant = await _stocked_variant(db, tenant_id)
    customer, _ = await _conversation(db, tenant_id)
    order = await _checkout_for(db, tenant_id, customer.id, variant)
    await db.execute(
        sql_text("UPDATE orders SET deleted_at = now() WHERE id = :id"), {"id": order.id}
    )
    await db.flush()

    result = await get_tool("get_my_orders").handler(
        db, tenant_id, context={"customer_id": str(customer.id)}
    )
    assert result["orders"] == []


async def test_get_my_orders_shows_what_the_cashier_took_back(db, tenant_ctx) -> None:
    """A real till sale then a real till return: the agent reports both truthfully."""
    from app.modules.catalog.service import CatalogService
    from app.modules.customers.service import CustomerService
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.service import PosService
    from tests._pos_sell import sell as pos_sell

    tenant_id = tenant_ctx.tenant_id
    warehouse = await InventoryService.get_default_warehouse(db, tenant_id)
    register = await PosService.create_register(
        db, tenant_id, name="كاشير", code=f"REG-{uuid.uuid4().hex[:6]}", warehouse_id=warehouse.id
    )
    till = await PosService.open_session(db, tenant_id, register.id)
    product = await CatalogService.create_product(
        db, tenant_id, title="تيشيرت", slug=f"t-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, title="مقاس ل", price="25.00"
    )
    await InventoryService.move(
        db, tenant_id, variant.id, warehouse.id, direction="in", quantity=10, reason="purchase"
    )
    customer = await CustomerService.create_from_import(
        db, tenant_id, name="زبون المرتجع", source="pos"
    )
    sold = await pos_sell(
        db,
        tenant_id,
        till.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    await PosService.return_sale(
        db,
        tenant_id,
        till.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )

    result = await get_tool("get_my_orders").handler(
        db, tenant_id, context={"customer_id": str(customer.id)}
    )

    assert len(result["orders"]) == 1
    row = result["orders"][0]
    assert row["grand_total"] == "50.00"
    assert row["items"][0]["quantity"] == 2
    assert row["returned"] == {"quantity": 1, "refund_total": "25.00"}
