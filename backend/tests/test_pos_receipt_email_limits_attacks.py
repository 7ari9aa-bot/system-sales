"""The receipt-email cap holds against respelling and against requests that arrive together.

Two ways round the first version, both found by attacking it: one Gmail inbox reached through
dots, a ``+tag`` or ``googlemail.com`` (31 sends against a cap of 20), and twelve simultaneous
requests on one receipt (all twelve passed a cap of 5, because count and insert were separate
steps). Providers other than Gmail are NOT merged: there a dot or ``+`` can be a different person.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import RateLimitExceededError
from app.modules.pos.service import PosService
from tests._pos_helpers import in_tx, make_tenant, purge_test_tenant
from tests.test_pos_receipt_email_limits import _ask, _sale
from tests.test_pos_record_sale_concurrency import _shelf

pytestmark = pytest.mark.asyncio

RACERS = 12


@pytest.fixture(autouse=True)
def _delivery_on(monkeypatch):
    monkeypatch.setattr(Settings, "auth_email_delivery_configured", property(lambda self: True))


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("vic@gmail.com", "v.i.c@gmail.com"),
        ("vic@gmail.com", "vic+promo@gmail.com"),
        ("vic@gmail.com", "VIC@googlemail.com"),
        ("v.i.c+a@gmail.com", "vi.c+b@googlemail.com"),
    ],
)
def test_one_gmail_inbox_has_one_key(a, b):
    assert PosService._receipt_email_key(a) == PosService._receipt_email_key(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("sam@example.com", "s.am@example.com"),
        ("sam@example.com", "sam+1@example.com"),
        ("vic@gmail.com", "vic@example.com"),
        ("vic@gmail.com", "vik@gmail.com"),
    ],
)
def test_other_providers_and_other_people_are_not_merged(a, b):
    assert PosService._receipt_email_key(a) != PosService._receipt_email_key(b)


async def test_respelling_a_gmail_inbox_does_not_buy_more_sends(db, tenant_ctx) -> None:
    spellings = [f"vic+{i}@gmail.com" for i in range(PosService.RECEIPT_EMAIL_PER_ADDRESS_PER_DAY)]
    for address in spellings:
        await _ask(db, tenant_ctx, await _sale(db, tenant_ctx), address)

    with pytest.raises(RateLimitExceededError):
        await _ask(db, tenant_ctx, await _sale(db, tenant_ctx), "v.i.c@googlemail.com")


async def test_two_different_people_on_another_provider_are_counted_apart(db, tenant_ctx) -> None:
    for _ in range(PosService.RECEIPT_EMAIL_PER_ADDRESS_PER_DAY):
        await _ask(db, tenant_ctx, await _sale(db, tenant_ctx), "sam@example.com")

    queued = await _ask(db, tenant_ctx, await _sale(db, tenant_ctx), "s.am@example.com")
    assert queued["queued"] is True


@pytest.fixture
async def shop(db_url, admin_url):
    engine, _f, tenant_id, user_id = await make_tenant(db_url, "em")
    big = create_async_engine(
        db_url, pool_size=RACERS + 3, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(big, expire_on_commit=False)
    try:
        yield factory, tenant_id, user_id
    finally:
        await big.dispose()
        await engine.dispose()
        await purge_test_tenant(admin_url, tenant_id, user_id)


async def test_requests_arriving_together_cannot_pass_the_per_receipt_cap(shop) -> None:
    factory, t, user = shop
    register_id, variant_id = await _shelf(factory, t, stock=5)

    async def sell(s):
        return await PosService.record_sale(
            s,
            t,
            register_id,
            items=[{"variant_id": str(variant_id), "quantity": 1}],
            actor_user_id=user,
        )

    sold = await in_tx(factory, t, sell)
    assert isinstance(sold, dict), sold
    receipt_id = sold["receipt_id"]

    async def ask(i):
        async def one(s):
            return await PosService.request_receipt_email(
                s, t, receipt_id, email=f"r{i}@example.com", requested_by=user
            )

        return await in_tx(factory, t, one)

    results = await asyncio.gather(*[ask(i) for i in range(RACERS)])

    queued = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, RateLimitExceededError)]
    other = [r for r in results if isinstance(r, Exception) and r not in refused]
    assert not other, other
    assert len(queued) == PosService.RECEIPT_EMAIL_PER_RECEIPT_PER_DAY
    assert len(refused) == RACERS - PosService.RECEIPT_EMAIL_PER_RECEIPT_PER_DAY

    stored = await in_tx(
        factory,
        t,
        lambda s: s.execute(
            text("select count(*) from outbox_events where payload->>'receipt_id' = :r"),
            {"r": str(receipt_id)},
        ),
    )
    assert stored.scalar_one() == PosService.RECEIPT_EMAIL_PER_RECEIPT_PER_DAY
