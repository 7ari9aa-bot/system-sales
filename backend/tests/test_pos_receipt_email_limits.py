"""A receipt can be emailed again, but not without limit.

"Email me this receipt" stages a real send from the merchant's own domain. With no ceiling, a till
could mail one receipt hundreds of times, or aim one address at a stranger from the shop's domain.
Two ceilings per rolling day, both counted from the requests already staged (nothing new is stored):
5 per receipt and 20 per address per shop. They guard abuse, they are not a shop policy.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.errors import RateLimitExceededError
from app.modules.pos.service import PosService
from tests._pos_helpers import till
from tests._pos_sell import sell

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _delivery_on(monkeypatch):
    monkeypatch.setattr(Settings, "auth_email_delivery_configured", property(lambda self: True))


async def _sale(db, tenant_ctx):
    shift, variant, _ = await till(db, tenant_ctx)
    sold = await sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        actor_user_id=tenant_ctx.user.id,
    )
    return sold["receipt_id"]


async def _ask(db, tenant_ctx, receipt_id, email):
    return await PosService.request_receipt_email(
        db, tenant_ctx.tenant_id, receipt_id, email=email, requested_by=tenant_ctx.user.id
    )


async def test_a_receipt_can_be_emailed_five_times_and_not_a_sixth(db, tenant_ctx) -> None:
    receipt_id = await _sale(db, tenant_ctx)
    for i in range(5):
        assert (await _ask(db, tenant_ctx, receipt_id, f"c{i}@example.com"))["queued"] is True

    with pytest.raises(RateLimitExceededError):
        await _ask(db, tenant_ctx, receipt_id, "c9@example.com")


async def test_the_same_address_is_counted_whatever_its_letter_case(db, tenant_ctx) -> None:
    # Cleaning lower-cases the domain but leaves the local part alone, so "Victim@" and "victim@"
    # reach the count as different strings. Most mail servers treat them as one mailbox, so the cap
    # must too, or changing one letter's case buys another 20 sends.
    for _ in range(20):
        receipt_id = await _sale(db, tenant_ctx)
        await _ask(db, tenant_ctx, receipt_id, "Victim@example.com")

    receipt_id = await _sale(db, tenant_ctx)
    with pytest.raises(RateLimitExceededError):
        await _ask(db, tenant_ctx, receipt_id, "victim@example.com")


async def test_one_address_is_capped_across_different_receipts(db, tenant_ctx) -> None:
    for _ in range(20):
        receipt_id = await _sale(db, tenant_ctx)
        await _ask(db, tenant_ctx, receipt_id, "stranger@example.com")

    receipt_id = await _sale(db, tenant_ctx)
    with pytest.raises(RateLimitExceededError):
        await _ask(db, tenant_ctx, receipt_id, "stranger@example.com")
    # A different address is unaffected.
    assert (await _ask(db, tenant_ctx, receipt_id, "other@example.com"))["queued"] is True


async def test_a_refused_request_stages_nothing(db, tenant_ctx) -> None:
    from sqlalchemy import func, select

    from app.modules.platform.models import OutboxEvent

    receipt_id = await _sale(db, tenant_ctx)
    for i in range(5):
        await _ask(db, tenant_ctx, receipt_id, f"c{i}@example.com")

    async def staged():
        return (
            await db.execute(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.payload["receipt_id"].astext == str(receipt_id))
            )
        ).scalar_one()

    before = await staged()
    with pytest.raises(RateLimitExceededError):
        await _ask(db, tenant_ctx, receipt_id, "c9@example.com")
    assert await staged() == before == 5


async def test_an_old_request_stops_counting_after_a_day(db, tenant_ctx) -> None:
    from sqlalchemy import update

    from app.modules.platform.models import OutboxEvent

    receipt_id = await _sale(db, tenant_ctx)
    for i in range(5):
        await _ask(db, tenant_ctx, receipt_id, f"c{i}@example.com")
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.payload["receipt_id"].astext == str(receipt_id))
        .values(created_at=OutboxEvent.created_at - timedelta(hours=25))
    )

    assert (await _ask(db, tenant_ctx, receipt_id, "later@example.com"))["queued"] is True


async def test_another_shops_requests_never_count_against_this_one(db, tenant_ctx) -> None:
    # The count is per shop: another shop mailing the same address must not use up this one's room.
    from uuid import uuid4

    from app.core.events.writer import add_outbox_event

    for _ in range(20):
        await add_outbox_event(
            db,
            aggregate_type="pos_session",
            aggregate_id=uuid4(),
            event_type="pos.receipt.email_requested",
            tenant_id=uuid4(),
            payload={
                "pos.receipt.email_requested": True,
                "receipt_id": str(uuid4()),
                "session_id": str(uuid4()),
                "email": "shared@example.com",
                "requested_by": None,
            },
            producer="pos",
        )

    receipt_id = await _sale(db, tenant_ctx)
    assert (await _ask(db, tenant_ctx, receipt_id, "shared@example.com"))["queued"] is True
