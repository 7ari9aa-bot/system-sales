"""A dead Instagram token must show up as a channel that needs reconnecting.

Before this: Meta answering 190 failed each message with a clear Arabic sentence, but the
channel kept reporting itself as active, so nobody was told to reconnect and every later
reply failed the same way. The worker now remembers that the refusal was a dead token and
moves a live channel to `reauth_required`.

The first half needs no database (what phase 2 records). The second half is DB-backed like
the other delivery-outcome tests: it skips locally and runs on CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.instagram import InstagramProviderError
from app.applications.apparel.modules.conversations.gateway.instagram_limits import classify_instagram_error
from app.applications.apparel.modules.conversations.service import ConversationService
from app.applications.apparel.modules.customers.models import Customer
from app.platform.platform.models import Integration
from app.workers.message_worker import MessageWorker, _SendPlan


def _error(code: int) -> InstagramProviderError:
    failure = classify_instagram_error({"error": {"code": code, "message": "x"}})
    return InstagramProviderError(f"instagram send failed [{failure.kind}]", failure)


class _Adapter:
    name = "instagram"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def send(self, credentials, outbound):
        raise self.exc


def _plan(exc: Exception) -> _SendPlan:
    outbound = OutboundMessage(
        tenant_id=MagicMock(),
        conversation_id=MagicMock(),
        message_id=MagicMock(),
        customer_ref="c1",
        body="hi",
    )
    return _SendPlan(
        adapter=_Adapter(exc),
        credentials=ProviderCredentials(config={}),
        outbound=outbound,
        set_channel_message_id=True,
    )


async def test_a_dead_token_is_remembered_by_the_plan() -> None:
    plan = _plan(_error(190))
    status, provider_id, _ = await MessageWorker(bus=MagicMock())._send(plan)
    assert (status, provider_id) == ("failed", None)
    assert plan.needs_reconnect is True


@pytest.mark.parametrize("code", [4, 100, 551])
async def test_other_refusals_do_not_ask_for_a_reconnect(code: int) -> None:
    plan = _plan(_error(code))
    await MessageWorker(bus=MagicMock())._send(plan)
    assert plan.needs_reconnect is False


async def test_a_plain_error_does_not_ask_for_a_reconnect() -> None:
    plan = _plan(RuntimeError("boom"))
    await MessageWorker(bus=MagicMock())._send(plan)
    assert plan.needs_reconnect is False


async def test_a_good_send_does_not_ask_for_a_reconnect() -> None:
    class _Ok(_Adapter):
        async def send(self, credentials, outbound):
            return "mid.1"

    plan = _plan(RuntimeError())
    plan.adapter = _Ok(RuntimeError())
    status, provider_id, _ = await MessageWorker(bus=MagicMock())._send(plan)
    assert (status, provider_id) == ("sent", "mid.1")
    assert plan.needs_reconnect is False


# ---- DB-backed: the channel row itself ---------------------------------------------


async def _instagram_message(db, tenant_id, status: str):
    db.add(
        Integration(
            tenant_id=tenant_id,
            provider="instagram",
            kind="channel",
            status=status,
            config={"account_id": "1784"},
        )
    )
    customer = Customer(tenant_id=tenant_id, name="Waiting Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="instagram"
    )
    # The customer wrote first: Instagram only lets a shop answer inside the 24h window that
    # their last inbound message opens, and the send policy refuses an outbound outside it.
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="hello",
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="ai",
        body="hi",
    )
    await db.flush()
    return message


async def _status(db, tenant_id) -> str:
    return (
        await db.execute(
            select(Integration.status).where(
                Integration.tenant_id == tenant_id, Integration.provider == "instagram"
            )
        )
    ).scalar_one()


async def test_a_live_channel_is_moved_to_reauth_required(db, tenant_ctx):
    message = await _instagram_message(db, tenant_ctx.tenant_id, "active")
    await MessageWorker(bus=MagicMock())._flag_channel_for_reconnect(
        db, tenant_ctx.tenant_id, message
    )
    await db.flush()
    assert await _status(db, tenant_ctx.tenant_id) == "reauth_required"


async def test_a_channel_in_another_state_is_left_alone(db, tenant_ctx):
    message = await _instagram_message(db, tenant_ctx.tenant_id, "disabled")
    await MessageWorker(bus=MagicMock())._flag_channel_for_reconnect(
        db, tenant_ctx.tenant_id, message
    )
    await db.flush()
    assert await _status(db, tenant_ctx.tenant_id) == "disabled"


async def test_no_channel_row_is_not_an_error(db, tenant_ctx):
    message = await _instagram_message(db, tenant_ctx.tenant_id, "active")
    await db.execute(Integration.__table__.delete())
    await MessageWorker(bus=MagicMock())._flag_channel_for_reconnect(
        db, tenant_ctx.tenant_id, message
    )
