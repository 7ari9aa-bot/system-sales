"""AI tool-surface tests (audit N-07).

Two layers:

* DB-free guards pin the CONTRACT of the registry — which tools exist, their
  honest risk levels, and above all that no customer-scoped tool lets the
  model name a customer (§132 scope binding).
* DB-backed tests prove the handlers actually read the bound tenant's rows and
  cannot reach another tenant's or another customer's. They skip when no
  database URL is configured; CI runs them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError, ValidationError
from app.modules.ai.tools import get_tool, requires_approval, tool_to_openai_schema
from app.modules.catalog.models import Product, ProductVariant
from app.modules.customers.service import CustomerService
from app.modules.operations.models import Task
from app.modules.orders.models import Order, OrderItem

# The tools N-07 added.
NEW_TOOLS = ("get_customer", "get_order", "search_knowledge", "add_task", "add_tag")


# ------------------------------------------------------- registry contract --


def test_new_tools_are_registered() -> None:
    for name in NEW_TOOLS:
        spec = get_tool(name)
        assert spec is not None, f"{name} is not registered"
        assert spec.name == name
        assert spec.description
        assert spec.args_schema is not None
        assert spec.handler is not None


@pytest.mark.parametrize(
    ("name", "risk"),
    [
        ("search_products", "LOW"),
        ("get_variant_price", "LOW"),
        ("check_stock", "LOW"),
        ("get_customer", "LOW"),
        ("get_order", "LOW"),
        ("search_knowledge", "LOW"),
        ("add_task", "MEDIUM"),
        ("add_tag", "MEDIUM"),
        ("create_order", "HIGH"),
    ],
)
def test_risk_levels_are_honest(name: str, risk: str) -> None:
    """Reads are LOW, record-creating writes MEDIUM, money/irreversible HIGH."""
    assert get_tool(name).risk_level == risk


async def test_only_high_risk_tools_require_approval() -> None:
    assert await requires_approval(get_tool("create_order")) is True
    for name in NEW_TOOLS:
        assert await requires_approval(get_tool(name)) is False


@pytest.mark.parametrize(
    ("name", "valid_args"),
    [
        ("get_customer", {}),
        ("get_order", {"order_id": str(uuid.uuid4())}),
        ("add_task", {"title": "Follow up"}),
        ("add_tag", {"tag": "vip"}),
    ],
)
def test_scoped_tools_never_expose_customer_id(name: str, valid_args: dict) -> None:
    """§132: the model must not be able to choose the customer.

    The schema omits customer_id, and even a model that sends one anyway has
    it dropped by the args schema before the handler ever runs.
    """
    spec = get_tool(name)
    properties = tool_to_openai_schema(spec)["function"]["parameters"]["properties"]
    assert "customer_id" not in properties
    dumped = spec.args_schema(**valid_args, **{"customer_id": str(uuid.uuid4())}).model_dump()
    assert "customer_id" not in dumped


def test_get_customer_takes_no_arguments() -> None:
    spec = get_tool("get_customer")
    properties = tool_to_openai_schema(spec)["function"]["parameters"]["properties"]
    assert properties == {}


def test_search_knowledge_cannot_ask_for_hidden_visibility() -> None:
    """§157: retrieval visibility is a server decision, not a model argument."""
    spec = get_tool("search_knowledge")
    properties = tool_to_openai_schema(spec)["function"]["parameters"]["properties"]
    assert "query" in properties
    assert "visibility" not in properties


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
    bad = {"customer_id": "not-a-uuid"}
    with pytest.raises(DomainError):
        await get_tool("get_customer").handler(None, uuid.uuid4(), context=bad)
    with pytest.raises(DomainError):
        await get_tool("add_tag").handler(None, uuid.uuid4(), tag="vip", context=bad)
    with pytest.raises(DomainError):
        await get_tool("add_task").handler(None, uuid.uuid4(), title="Follow up", context=bad)
    with pytest.raises(DomainError):
        await get_tool("get_order").handler(None, uuid.uuid4(), order_id=uuid.uuid4(), context=bad)


# ------------------------------------------------------------ DB-backed -----


async def _customer(db: AsyncSession, tenant_id: uuid.UUID, name: str = "Nour"):
    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name=name
    )


async def _order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    total: str = "100.00",
) -> Order:
    order = Order(
        tenant_id=tenant_id,
        customer_id=customer_id,
        number=f"ORD-{uuid.uuid4().hex[:8]}",
        status="confirmed",
        currency="EGP",
        grand_total=Decimal(total),
    )
    db.add(order)
    await db.flush()
    return order


async def _variant(db: AsyncSession, tenant_id: uuid.UUID) -> ProductVariant:
    product = Product(tenant_id=tenant_id, title="Widget", slug=f"w-{uuid.uuid4().hex[:8]}")
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"W-{uuid.uuid4().hex[:6].upper()}",
        title="Widget M",
        price=Decimal("25.50"),
    )
    db.add(variant)
    await db.flush()
    return variant


async def test_get_customer_returns_the_bound_customer(db: AsyncSession, tenant_ctx) -> None:
    customer = await _customer(db, tenant_ctx.tenant_id, name="Bound Customer")
    spec = get_tool("get_customer")
    result = await spec.handler(db, tenant_ctx.tenant_id, context={"customer_id": str(customer.id)})
    assert result["customer_id"] == str(customer.id)
    assert result["name"] == "Bound Customer"
    assert result["lifetime_value"] == str(customer.lifetime_value)


async def test_get_customer_without_a_binding_is_refused(db: AsyncSession, tenant_ctx) -> None:
    spec = get_tool("get_customer")
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_ctx.tenant_id, context=None)
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_ctx.tenant_id, context={"customer_id": None})


async def test_get_customer_cannot_read_another_tenant(db: AsyncSession, tenant_ctx) -> None:
    customer = await _customer(db, tenant_ctx.tenant_id)
    spec = get_tool("get_customer")
    with pytest.raises(NotFoundError):
        await spec.handler(db, uuid.uuid4(), context={"customer_id": str(customer.id)})


async def test_get_order_returns_the_bound_customers_order(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)
    order = await _order(db, tenant_id, customer.id, total="150.00")
    variant = await _variant(db, tenant_id)
    db.add(
        OrderItem(
            tenant_id=tenant_id,
            order_id=order.id,
            variant_id=variant.id,
            title="Widget M",
            sku=variant.sku,
            quantity=2,
            unit_price=Decimal("25.50"),
            total=Decimal("51.00"),
        )
    )
    await db.flush()

    spec = get_tool("get_order")
    result = await spec.handler(
        db, tenant_id, order_id=order.id, context={"customer_id": str(customer.id)}
    )
    assert result["order_id"] == str(order.id)
    assert result["grand_total"] == "150.00"
    assert result["items"] == [
        {
            "title": "Widget M",
            "sku": variant.sku,
            "quantity": 2,
            "unit_price": "25.50",
            "total": "51.00",
        }
    ]


async def test_get_order_refuses_another_customers_order(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    mine = await _customer(db, tenant_id, name="Mine")
    theirs = await _customer(db, tenant_id, name="Theirs")
    their_order = await _order(db, tenant_id, theirs.id)

    spec = get_tool("get_order")
    with pytest.raises(NotFoundError):
        await spec.handler(
            db, tenant_id, order_id=their_order.id, context={"customer_id": str(mine.id)}
        )
    # With no binding at all the call is refused, never defaulted.
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_id, order_id=their_order.id, context=None)


async def test_get_order_cannot_read_another_tenant(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)
    order = await _order(db, tenant_id, customer.id)
    spec = get_tool("get_order")
    with pytest.raises(NotFoundError):
        await spec.handler(
            db, uuid.uuid4(), order_id=order.id, context={"customer_id": str(customer.id)}
        )


async def test_add_task_links_the_bound_customer(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)
    spec = get_tool("add_task")
    kwargs = spec.args_schema(title="Call back tomorrow", priority=1).model_dump()
    result = await spec.handler(db, tenant_id, **kwargs, context={"customer_id": str(customer.id)})

    task = (
        await db.execute(select(Task).where(Task.id == uuid.UUID(result["task_id"])))
    ).scalar_one()
    assert task.tenant_id == tenant_id
    assert task.title == "Call back tomorrow"
    assert task.priority == 1
    assert task.status == "todo"
    assert task.source == "ai"
    assert task.related_entity_type == "customer"
    assert task.related_entity_id == customer.id


async def test_add_task_without_a_binding_creates_no_customer_link(
    db: AsyncSession, tenant_ctx
) -> None:
    spec = get_tool("add_task")
    kwargs = spec.args_schema(title="Restock the shelves").model_dump()
    result = await spec.handler(db, tenant_ctx.tenant_id, **kwargs, context=None)

    task = (
        await db.execute(select(Task).where(Task.id == uuid.UUID(result["task_id"])))
    ).scalar_one()
    assert task.tenant_id == tenant_ctx.tenant_id
    assert task.related_entity_id is None


async def test_add_tag_uses_the_bound_customer(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _customer(db, tenant_id)
    spec = get_tool("add_tag")
    result = await spec.handler(db, tenant_id, tag="vip", context={"customer_id": str(customer.id)})
    assert result == {"customer_id": str(customer.id), "tag": "vip"}

    tags = await CustomerService.list_tags(db, tenant_id, customer.id)
    assert [tag.name for tag in tags] == ["vip"]


async def test_add_tag_without_a_binding_is_refused(db: AsyncSession, tenant_ctx) -> None:
    spec = get_tool("add_tag")
    with pytest.raises(DomainError):
        await spec.handler(db, tenant_ctx.tenant_id, tag="vip", context=None)


# --------------------------------------------- LIKE escaping (A7, DB-free) --


class _CapturingSession:
    """Records the statement ``_search_products`` builds; returns no rows.

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

    def first(self):  # noqa: ANN201
        return None


def _search_patterns(query: str) -> tuple[str, list[str]]:
    """Compile ``_search_products``'s SELECT for ``query`` offline.

    Returns (rendered SQL, every string bound param) so a test can assert the
    LIKE pattern reaches the driver escaped, and that the statement declares an
    ESCAPE clause (without it a backslash is literal text, not an escape).
    """
    import asyncio

    from sqlalchemy.dialects import postgresql

    from app.modules.ai.tools import _search_products

    session = _CapturingSession()
    asyncio.run(_search_products(session, uuid.uuid4(), query=query, limit=5))
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
def test_search_products_escapes_like_wildcards(query: str, expected_core: str) -> None:
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


def test_search_products_percent_query_does_not_match_everything() -> None:
    """The concrete A7 attack: query='%' must not become a match-all pattern.

    Unescaped, the pattern was '%%%' (matches every row). Escaped, it is
    '%\\%%' — rows whose title/sku literally contain a percent sign.
    """
    _, params = _search_patterns("%")
    assert "%%%" not in params, f"match-all pattern bound: {params!r}"
    assert r"%\%%" in params, params
