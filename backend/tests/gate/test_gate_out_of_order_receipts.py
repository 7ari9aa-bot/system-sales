"""§176 gate scenario 6 — out-of-order provider events (§129, §130).

Providers deliver receipts late, twice, and in the wrong order. §130 says a
receipt may only move a message FORWARD, and that a `read` arriving before
`sent` must still leave the message `read` once the late `sent` shows up.

`_apply_status_updates` implements that as a monotonic state machine, but its
only tests were on the adapter's *parsing* — nothing exercised the state
machine itself, so the "never regress" guarantee was untested.

DB-backed (real PostgreSQL, RLS enforced); skips via the shared `db_url` fixture.
"""

from __future__ import annotations

import itertools
import uuid

import pytest
from sqlalchemy import select

from app.modules.conversations.gateway.base import StatusUpdate
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer

# §22 moved the state machine out of router._apply_status_updates.
_apply_status_updates = IngestService.apply_status_updates

pytestmark = [pytest.mark.gate]

FORWARD_ORDER = ["sent", "delivered", "read"]


async def _outbound(db, tenant_ctx, *, status: str = "sending") -> str:
    """Insert one outbound message awaiting receipts; return its provider id."""
    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Receipts")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    wamid = f"wamid.{uuid.uuid4().hex}"
    db.add(
        Message(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="agent",
            channel_message_id=wamid,
            body="hello",
            status=status,
        )
    )
    await db.flush()
    return wamid


async def _status(db, tenant_ctx, wamid: str) -> str:
    return (
        await db.execute(
            select(Message.status).where(
                Message.tenant_id == tenant_ctx.tenant_id,
                Message.channel_message_id == wamid,
            )
        )
    ).scalar_one()


async def _deliver(db, tenant_ctx, wamid: str, *statuses: str, error: str | None = None):
    for status in statuses:
        await _apply_status_updates(
            db,
            tenant_ctx.tenant_id,
            [StatusUpdate(channel_message_id=wamid, status=status, error=error)],
        )


async def test_in_order_receipts_advance_to_read(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    for expected in FORWARD_ORDER:
        await _deliver(db, tenant_ctx, wamid, expected)
        assert await _status(db, tenant_ctx, wamid) == expected


@pytest.mark.parametrize(
    "arrival", list(itertools.permutations(FORWARD_ORDER)), ids=lambda p: "-".join(p)
)
async def test_any_arrival_order_converges_on_read(db, tenant_ctx, arrival):
    """All 6 orderings of sent/delivered/read must end at `read` — never earlier."""
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, wamid, *arrival)
    assert await _status(db, tenant_ctx, wamid) == "read"


async def test_a_late_receipt_never_regresses_the_status(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, wamid, "read")
    for late in ("sent", "delivered", "sent", "delivered"):
        await _deliver(db, tenant_ctx, wamid, late)
        assert await _status(db, tenant_ctx, wamid) == "read", f"regressed on late {late!r}"


async def test_replaying_the_same_receipt_is_idempotent(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, wamid, "delivered", "delivered", "delivered")
    assert await _status(db, tenant_ctx, wamid) == "delivered"


async def test_unknown_send_result_is_reconciled_by_a_delivery_receipt(db, tenant_ctx):
    """§129: after a lost send result the message is UNKNOWN, and the provider's
    receipt is what resolves it — without a resend."""
    wamid = await _outbound(db, tenant_ctx, status="unknown")
    await _deliver(db, tenant_ctx, wamid, "delivered")
    assert await _status(db, tenant_ctx, wamid) == "delivered"


async def test_a_delivered_message_cannot_be_marked_failed_by_a_stray_receipt(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, wamid, "delivered")
    await _deliver(db, tenant_ctx, wamid, "failed", error="stray")
    assert await _status(db, tenant_ctx, wamid) == "delivered"


async def test_a_failed_receipt_records_the_error_for_an_unsent_message(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx, status="sending")
    await _deliver(db, tenant_ctx, wamid, "failed", error="131047 re-engagement window")
    assert await _status(db, tenant_ctx, wamid) == "failed"
    error = (
        await db.execute(
            select(Message.error).where(
                Message.tenant_id == tenant_ctx.tenant_id,
                Message.channel_message_id == wamid,
            )
        )
    ).scalar_one()
    assert error == "131047 re-engagement window"


async def test_an_unrecognised_provider_status_is_never_written_raw(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, wamid, "banana", "'; DROP TABLE messages; --")
    assert await _status(db, tenant_ctx, wamid) == "sending"


async def test_a_receipt_for_an_unknown_message_is_ignored(db, tenant_ctx):
    wamid = await _outbound(db, tenant_ctx)
    await _deliver(db, tenant_ctx, "wamid.does-not-exist", "read")  # must not raise
    assert await _status(db, tenant_ctx, wamid) == "sending"
