"""CustomerService tests — identity dedup, phone attach, tags/notes/events."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import (
    CustomerEvent,
    CustomerIdentity,
    Note,
    Tag,
    customer_tags,
)
from app.modules.customers.service import CustomerService
from app.modules.errors import NotFoundError


async def _identity_count(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> int:
    rows = (
        await db.execute(
            select(CustomerIdentity).where(
                CustomerIdentity.tenant_id == tenant_id,
                CustomerIdentity.customer_id == customer_id,
            )
        )
    ).scalars().all()
    return len(rows)


async def test_get_or_create_by_identity_dedups(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    external_id = f"wa-{uuid.uuid4().hex[:10]}"

    first = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", external_id, name="Nour", phone="+201000000001"
    )
    second = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", external_id
    )

    assert second.id == first.id
    assert first.name == "Nour"
    assert first.phone == "+201000000001"
    assert first.last_seen_at is not None
    assert await _identity_count(db, tenant_id, first.id) == 1
    await db.flush()


async def test_same_phone_attaches_identity_to_existing_customer(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    phone = f"+2011{uuid.uuid4().hex[:8]}"

    by_whatsapp = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Sameer", phone=phone
    )
    by_instagram = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "instagram", f"ig-{uuid.uuid4().hex[:10]}", phone=phone
    )

    assert by_instagram.id == by_whatsapp.id
    assert await _identity_count(db, tenant_id, by_whatsapp.id) == 2
    await db.flush()


async def test_name_backfills_while_empty(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    external_id = f"web-{uuid.uuid4().hex[:10]}"

    anonymous = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "webchat", external_id
    )
    assert anonymous.name == ""

    named = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "webchat", external_id, name="Hana"
    )
    assert named.id == anonymous.id
    assert named.name == "Hana"
    await db.flush()


async def test_add_tag_is_idempotent_and_remove_works(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Tagged"
    )

    tag = await CustomerService.add_tag(db, tenant_id, customer.id, "vip")
    await CustomerService.add_tag(db, tenant_id, customer.id, "vip")  # no dup link
    await CustomerService.add_tag(db, tenant_id, customer.id, "wholesale")

    links = (
        await db.execute(
            select(customer_tags).where(customer_tags.c.customer_id == customer.id)
        )
    ).all()
    assert len(links) == 2
    tags = (
        await db.execute(select(Tag).where(Tag.tenant_id == tenant_id))
    ).scalars().all()
    assert {t.name for t in tags} == {"vip", "wholesale"}
    assert tag.name == "vip"

    await CustomerService.remove_tag(db, tenant_id, customer.id, "vip")
    remaining = (
        await db.execute(
            select(customer_tags).where(customer_tags.c.customer_id == customer.id)
        )
    ).all()
    assert len(remaining) == 1
    await db.flush()


async def test_add_note_and_record_event(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )

    note = await CustomerService.add_note(
        db, tenant_id, customer.id, tenant_ctx.user.id, "Prefers evening delivery"
    )
    assert note.body == "Prefers evening delivery"
    assert note.author_user_id == tenant_ctx.user.id
    stored_note = (
        await db.execute(select(Note).where(Note.id == note.id))
    ).scalar_one()
    assert stored_note.customer_id == customer.id

    event = await CustomerService.record_event(
        db, tenant_id, customer.id, "message.received", {"text": "hello"}
    )
    assert event.event_type == "message.received"
    assert event.payload == {"text": "hello"}
    stored_event = (
        await db.execute(select(CustomerEvent).where(CustomerEvent.id == event.id))
    ).scalar_one()
    assert stored_event.customer_id == customer.id
    await db.flush()


async def test_get_enforces_tenant_scope(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Scoped"
    )

    found = await CustomerService.get(db, tenant_id, customer.id)
    assert found.id == customer.id

    with pytest.raises(NotFoundError):
        await CustomerService.get(db, uuid.uuid4(), customer.id)  # other tenant
    with pytest.raises(NotFoundError):
        await CustomerService.get(db, tenant_id, uuid.uuid4())  # missing
    await db.flush()


async def test_list_customers_search(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    suffix = uuid.uuid4().hex[:8]
    target = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{suffix}", name=f"Zaki {suffix}"
    )
    await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-other-{suffix}", name="Someone Else"
    )

    hit = await CustomerService.list_customers(db, tenant_id, search=f"Zaki {suffix}")
    assert [c.id for c in hit] == [target.id]

    everyone = await CustomerService.list_customers(db, tenant_id, limit=100)
    assert {c.id for c in everyone} >= {target.id}
    await db.flush()
