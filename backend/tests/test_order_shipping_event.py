"""Item A — a shipping correction on an open order must say so on the bus.

``PATCH /orders/{id}/shipping`` writes the row and an ``audit_logs`` line, and
until now it published NOTHING: the event type it wanted
(``order.shipping_updated``) is not in ``DOMAIN_EVENT_TYPES``, so
``build_envelope`` would have refused it inside the writer — which is exactly
how the omission stayed invisible (the code never reached the refusal; it just
never called the writer).

A silent row update is the bug class this file kills. Every other order
mutation commits its outbox row in the SAME transaction as the change
(``order.created``, ``order.status_changed``, ``order.refunded``), so a
consumer watching ``order.events`` can rebuild an order's history from the
stream alone. A corrected address that never reaches the stream is the one
fact about a live order the stream does not carry, and anything downstream
(the relay, the SSE client, an automation re-printing a label) keeps
shipping to the address the merchant just struck out.

Structure: the first block is DB-free and runs locally; the rest is DB-backed
and runs in CI (skips locally without ``DATABASE_URL_APP_ADMIN``).
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import Integer, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.schemas import DOMAIN_EVENT_TYPES, EVENT_TYPES, deserialize
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.inventory.service import InventoryService
from app.modules.orders import service as orders_service
from app.modules.orders.models import Order
from app.modules.orders.service import _SHIPPING_EDITABLE_STATUSES, OrderService
from app.modules.platform.models import AuditLog, OutboxEvent
from tests.test_order_idempotency import SessionStore, _build_app

EVENT_TYPE = "order.shipping_updated"
SERVICE_FILE = pathlib.Path(orders_service.__file__)
_NEW_ADDRESS = {"city": "Alexandria", "street": "Rami 12"}


# ------------------------------------------------------- DB-free: registry ----


def test_the_shipping_event_type_is_registered() -> None:
    """The writer refuses an unregistered type, so the type must be declared.

    Registering it in ``DOMAIN_EVENT_TYPES`` is also what makes the §144
    fairness tier and the AST scan in ``test_campaign_fairness.py`` see the
    call site — an event type that exists only as a string in one module is a
    contract nothing enforces.
    """
    assert EVENT_TYPE in DOMAIN_EVENT_TYPES
    # ... and it resolves to the envelope class the other order events use.
    assert EVENT_TYPE in EVENT_TYPES


def test_the_shipping_writer_stages_the_event_in_the_mutation_transaction() -> None:
    """Same session, same transaction, no commit of its own.

    ``update_shipping`` must call the shared ``add_outbox_event`` writer (the
    only door to the outbox) rather than hand-merge a row or hand-publish to
    Redis. The outbox row is flushed with the UPDATE, so "the address changed"
    and "the stream knows" commit together or not at all.
    """
    call = _shipping_outbox_call()
    assert call is not None, f"{EVENT_TYPE} is never staged from update_shipping"
    assert call["event_type"] == EVENT_TYPE, call["event_type"]
    assert call["awaited"], "add_outbox_event is async; an unawaited call is a no-op"
    assert not _update_shipping_commits(), "a service method must never commit"


def test_only_an_open_order_can_have_its_shipping_changed():
    """The event is emitted for an order that has not left, and never claims
    the parcel moved: `shipped` and beyond is history on this row."""
    assert _SHIPPING_EDITABLE_STATUSES == {"pending", "confirmed", "processing"}
    assert "shipped" not in _SHIPPING_EDITABLE_STATUSES


# ---------------------------------------------------------------- fixtures ----


async def _order(
    db: AsyncSession, tenant_id: uuid.UUID, *, address: dict | None = None
) -> Order:
    """A placed order with a Cairo address, the row the PATCH corrects."""
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )
    product = await CatalogService.create_product(
        db, tenant_id, title="Ship Me", slug=f"s-{uuid.uuid4().hex[:10]}"
    )
    # §M4: checkout refuses a draft product, and `draft` is the column default.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, price="40.00"
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        (await InventoryService.get_default_warehouse(db, tenant_id)).id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
        shipping_address=address,
    )


async def _stored_version(db: AsyncSession, order_id: uuid.UUID) -> int:
    """The version on the ROW, not on the instance the service handed back."""
    return (
        await db.execute(select(Order.version).where(Order.id == order_id))
    ).scalar_one()


async def _events(
    db: AsyncSession, order_id: uuid.UUID, event_type: str = EVENT_TYPE
) -> list[OutboxEvent]:
    """The aggregate's event stream, in the order the events happened.

    Ordered by §153 `meta.aggregate_version`, NOT by the row id: `id` is a
    `uuid4`, so ordering by it returns rows in an order that only looks stable.
    CI caught a test asserting `events[1]` is the newest and getting whichever
    random UUID sorted second.
    """
    version = cast(OutboxEvent.meta["aggregate_version"].astext, Integer)
    return list(
        (
            await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.aggregate_type == "order",
                    OutboxEvent.aggregate_id == order_id,
                    OutboxEvent.payload["event_type"].astext == event_type,
                )
                .order_by(version.asc())
            )
        )
        .scalars()
        .all()
    )


async def _audit_rows(db: AsyncSession, order_id: uuid.UUID) -> list[AuditLog]:
    return list(
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.resource_type == "order",
                    AuditLog.resource_id == str(order_id),
                    AuditLog.action == EVENT_TYPE,
                )
            )
        )
        .scalars()
        .all()
    )


async def _patch(app: Any, order_id: uuid.UUID, payload: dict) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.patch(
            f"/api/v1/orders/{order_id}/shipping", json=payload
        )


# --------------------------------------------------------- DB: the PATCH ----


async def test_the_shipping_patch_stages_exactly_one_event(
    db: AsyncSession, tenant_ctx
):
    """One PATCH, one envelope naming the new address and the real version."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id, address={"city": "Cairo", "street": "Tahrir 9"})
    before_version = await _stored_version(db, order.id)
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )

    response = await _patch(
        app,
        order.id,
        {"shipping_address": _NEW_ADDRESS, "shipping_method": "courier"},
    )
    assert response.status_code == 200, response.text
    await db.flush()

    events = await _events(db, order.id)
    assert len(events) == 1, [e.id for e in events]
    event = events[0]
    # The stream is DERIVED from aggregate_type by the writer: this is the
    # stream the relay publishes and the SSE gateway fans out.
    assert event.stream == "order.events"
    assert event.status == "pending"
    assert event.payload["event_type"] == EVENT_TYPE
    assert event.payload["order_id"] == str(order.id)
    assert event.payload["number"] == order.number
    assert event.payload["shipping_address"] == _NEW_ADDRESS
    assert event.payload["shipping_method"] == "courier"
    # The address the merchant struck out: a consumer must be able to tell
    # "where it went" from "where it is going" without replaying history.
    assert event.payload["previous_shipping_address"] == {
        "city": "Cairo",
        "street": "Tahrir 9",
    }

    # §153: the order row's REAL post-mutation version — never a literal.
    after_version = await _stored_version(db, order.id)
    assert after_version == before_version + 1
    assert event.meta["aggregate_version"] == after_version
    assert event.meta["type"] == EVENT_TYPE
    assert event.meta["tenant_id"] == str(tenant_id)

    assert len(await _audit_rows(db, order.id)) == 1


async def test_the_event_rebuilds_through_the_consumer_read_half(
    db: AsyncSession, tenant_ctx
):
    """The stored row IS what the relay/SSE consumer reads back.

    The gateway and the relay both go through ``deserialize``; an event the
    writer can stage but a consumer cannot rebuild never reaches a client, so
    the round trip is asserted on the real row rather than on a hand-built one.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )

    await _patch(app, order.id, {"shipping_address": _NEW_ADDRESS})
    await db.flush()
    event = (await _events(db, order.id))[0]

    envelope = deserialize({"payload": event.payload, "meta": event.meta})

    assert envelope.type == EVENT_TYPE
    assert envelope.aggregate_type == "order"
    assert envelope.aggregate_id == order.id
    assert envelope.tenant_id == tenant_id
    assert envelope.aggregate_version == await _stored_version(db, order.id)
    assert envelope.payload["shipping_address"] == _NEW_ADDRESS


async def test_a_second_identical_patch_stages_no_duplicate_event(
    db: AsyncSession, tenant_ctx
):
    """The same address twice is one change, not two.

    A PATCH has no ``Idempotency-Key`` (``/api/v1/orders/{id}/shipping`` is not
    on ``IDEMPOTENT_PATHS``), so the retry-safe answer has to come from the
    mutation itself: when the values the caller sent are the values the row
    already holds, nothing changed — so no version bump, no audit row, and no
    event claiming one.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id, address={"city": "Cairo"})
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )
    body = {"shipping_address": _NEW_ADDRESS, "shipping_method": "courier"}

    first = await _patch(app, order.id, body)
    assert first.status_code == 200, first.text
    await db.flush()
    version_after_first = await _stored_version(db, order.id)
    assert len(await _events(db, order.id)) == 1

    second = await _patch(app, order.id, body)
    assert second.status_code == 200, second.text
    await db.flush()

    assert len(await _events(db, order.id)) == 1, "a no-op PATCH published a change"
    assert await _stored_version(db, order.id) == version_after_first
    assert len(await _audit_rows(db, order.id)) == 1


async def test_a_real_change_after_a_no_op_still_publishes(
    db: AsyncSession, tenant_ctx
):
    """The no-op guard must not swallow the change that follows it."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id, address={"city": "Cairo"})
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )

    await _patch(app, order.id, {"shipping_address": _NEW_ADDRESS})
    await db.flush()
    await _patch(app, order.id, {"shipping_address": _NEW_ADDRESS})
    await db.flush()
    assert len(await _events(db, order.id)) == 1

    third = {"city": "Giza", "street": "Nile 1"}
    response = await _patch(app, order.id, {"shipping_address": third})
    assert response.status_code == 200, response.text
    await db.flush()

    events = await _events(db, order.id)
    assert len(events) == 2
    assert events[1].payload["shipping_address"] == third
    assert events[1].payload["previous_shipping_address"] == _NEW_ADDRESS
    assert events[1].meta["aggregate_version"] == await _stored_version(db, order.id)


async def test_an_event_is_staged_for_a_method_only_change(
    db: AsyncSession, tenant_ctx
):
    """``shipping_method`` lives in ``extra``; a method-only change is still a
    change the fulfilment side cares about (courier vs. own rider)."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )

    response = await _patch(app, order.id, {"shipping_method": "own_rider"})
    assert response.status_code == 200, response.text
    await db.flush()

    events = await _events(db, order.id)
    assert len(events) == 1
    assert events[0].payload["shipping_method"] == "own_rider"
    # The untouched half of the pair is reported as what it still is, not null.
    assert events[0].payload["shipping_address"] == order.shipping_address


# ------------------------------------------------------ DB-free: AST scans ----


def _update_shipping_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse(SERVICE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_shipping":
            return node
    raise AssertionError("OrderService.update_shipping is gone")


def _shipping_outbox_call() -> dict[str, Any] | None:
    """The add_outbox_event call inside update_shipping, if there is one."""
    fn = _update_shipping_fn()
    awaited = {
        id(node.value) for node in ast.walk(fn) if isinstance(node, ast.Await)
    }
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "add_outbox_event"
        ):
            event_type = next(
                (
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg == "event_type" and isinstance(kw.value, ast.Constant)
                ),
                None,
            )
            return {"event_type": event_type, "awaited": id(node) in awaited}
    return None


def _update_shipping_commits() -> bool:
    """A commit inside the mutation would split it away from the outbox row."""
    return any(
        isinstance(node, ast.Attribute) and node.attr in {"commit", "rollback"}
        for node in ast.walk(_update_shipping_fn())
    )
