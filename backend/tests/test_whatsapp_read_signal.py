"""Blue ticks and "typing…" on the CUSTOMER's phone, sent through the Cloud API.

Both are one Meta request (status: read + typing_indicator). They are visible to the
customer, so the rules matter: WhatsApp only, only the newest real customer message,
only inside the 24h window, and a failure never blocks the agent.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.core.errors import PermissionDeniedError
from app.applications.apparel.modules.conversations.gateway.base import ExternalProviderError, ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.applications.apparel.modules.conversations.models import Conversation, Message
from app.applications.apparel.modules.conversations.read_signal_service import ReadSignalService
from app.applications.apparel.modules.conversations.routers._deps import ReadSignalRequest
from app.applications.apparel.modules.conversations.routers.inbox import router, send_read_signal
from tests._pos_helpers import ctx_for
from tests.test_whatsapp_staff_reply_send import _customer_message

adapter = WhatsAppAdapter()
CREDS = ProviderCredentials(config={"phone_number_id": "1065", "access_token": "tok"})


# ---- the request Meta receives (no database) -------------------------------------


def test_read_only_is_status_read_with_the_message_id() -> None:
    assert adapter.build_read_signal("wamid.A", typing=False) == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.A",
    }


def test_typing_adds_the_typing_indicator_to_the_same_request() -> None:
    body = adapter.build_read_signal("wamid.A", typing=True)
    assert body["status"] == "read" and body["message_id"] == "wamid.A"
    assert body["typing_indicator"] == {"type": "text"}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_it_posts_to_the_phone_number_with_the_bearer_token() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    await adapter.send_read_signal(CREDS, "wamid.A", typing=True, _client=_client(handler))
    assert seen["url"].endswith("/1065/messages")
    assert seen["auth"] == "Bearer tok"
    assert seen["json"]["typing_indicator"] == {"type": "text"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": {"message": "bad id"}}),
        httpx.Response(200, json={"error": {"message": "nope"}}),
        httpx.Response(200, json={"success": False}),
        httpx.Response(200, text="<html>gateway</html>"),
    ],
)
async def test_a_rejection_or_an_unclear_answer_is_an_error(response) -> None:
    with pytest.raises(ExternalProviderError):
        await adapter.send_read_signal(
            CREDS, "wamid.A", typing=False, _client=_client(lambda r: response)
        )


@pytest.mark.asyncio
async def test_missing_credentials_or_message_id_is_an_error_before_any_request() -> None:
    def boom(request):
        raise AssertionError("no request should be made")

    with pytest.raises(ExternalProviderError):
        await adapter.send_read_signal(
            ProviderCredentials(config={}), "wamid.A", typing=False, _client=_client(boom)
        )
    with pytest.raises(ExternalProviderError):
        await adapter.send_read_signal(CREDS, "", typing=False, _client=_client(boom))


# ---- the rules around it (database) ----------------------------------------------


class _Spy:
    """Stands in for the adapter so no network is touched."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.fail = False

    async def send_read_signal(self, credentials, provider_message_id, *, typing):
        if self.fail:
            raise RuntimeError("meta down")
        self.calls.append((provider_message_id, typing))


@pytest.fixture
def spy(monkeypatch):
    s = _Spy()
    monkeypatch.setattr("app.applications.apparel.modules.conversations.read_signal_service.get_adapter", lambda name: s)

    async def _decrypt(session, integration):
        return {"phone_number_id": "1065", "access_token": "tok"}

    monkeypatch.setattr(
        "app.modules.platform.service.IntegrationCredentialsService.decrypt", _decrypt
    )
    return s


async def _connect(db, tenant_id) -> None:
    from app.modules.platform.models import Integration

    db.add(Integration(tenant_id=tenant_id, provider="whatsapp", kind="channel", config={}))
    await db.flush()


async def _chat(db, tenant_ctx, wamid="wamid.NEWEST"):
    await _connect(db, tenant_ctx.tenant_id)
    return await _customer_message(db, tenant_ctx.tenant_id, "201001234567", wamid, "hello")


async def _conversation(db, conversation_id) -> Conversation:
    return (
        await db.execute(sa.select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_opening_a_chat_sends_the_read_receipt_only(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    out = await send_read_signal(cid, ReadSignalRequest(typing=False), ctx=ctx)
    assert out == {"sent": True, "skipped": None}
    assert spy.calls == [("wamid.NEWEST", False)]


@pytest.mark.asyncio
async def test_typing_sends_the_indicator(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    await send_read_signal(cid, ReadSignalRequest(typing=True), ctx=ctx)
    assert spy.calls == [("wamid.NEWEST", True)]


@pytest.mark.asyncio
async def test_it_refers_to_the_newest_customer_message(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx, "wamid.FIRST")
    second = await _customer_message(
        db, tenant_ctx.tenant_id, "201001234567", "wamid.SECOND", "again"
    )
    assert second == cid
    # Stored in one instant, as a webhook batch is: only the provider's own time differs.
    rows = (
        (await db.execute(sa.select(Message).where(Message.conversation_id == cid))).scalars().all()
    )
    same = rows[0].created_at
    for m in rows:
        m.created_at = same
        m.payload = {
            "raw": {
                "timestamp": "1700000009"
                if m.channel_message_id == "wamid.SECOND"
                else "1700000001"
            }
        }
    await db.flush()
    ctx = await ctx_for(db, tenant_ctx, "owner")
    await send_read_signal(cid, ReadSignalRequest(), ctx=ctx)
    assert spy.calls[0][0] == "wamid.SECOND"


@pytest.mark.asyncio
async def test_outside_the_24h_window_nothing_is_sent(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx)
    (await _conversation(db, cid)).last_customer_message_at = datetime.now(UTC) - timedelta(
        hours=25
    )
    await db.flush()
    ctx = await ctx_for(db, tenant_ctx, "owner")
    out = await send_read_signal(cid, ReadSignalRequest(typing=True), ctx=ctx)
    assert out == {"sent": False, "skipped": "window_closed"}
    assert spy.calls == []


@pytest.mark.asyncio
async def test_another_channel_is_left_alone(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx)
    conv = await _conversation(db, cid)
    conv.channel = "telegram"
    await db.flush()
    out = await ReadSignalService.send(db, tenant_ctx.tenant_id, conv, typing=True)
    assert (out.sent, out.skipped) == (False, "channel")
    assert spy.calls == []


@pytest.mark.asyncio
async def test_no_whatsapp_connection_sends_nothing(db, tenant_ctx, spy) -> None:
    cid = await _customer_message(db, tenant_ctx.tenant_id, "201009998877", "wamid.X", "hi")
    out = await ReadSignalService.send(
        db, tenant_ctx.tenant_id, await _conversation(db, cid), typing=False
    )
    assert (out.sent, out.skipped) == (False, "not_connected")


@pytest.mark.asyncio
async def test_a_provider_failure_is_reported_not_raised(db, tenant_ctx, spy) -> None:
    spy.fail = True
    cid = await _chat(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    out = await send_read_signal(cid, ReadSignalRequest(typing=True), ctx=ctx)
    assert out == {"sent": False, "skipped": "provider_error"}


@pytest.mark.asyncio
async def test_a_reaction_is_not_a_message_to_mark_read(db, tenant_ctx, spy) -> None:
    cid = await _chat(db, tenant_ctx, "wamid.REAL")
    db.add(
        Message(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=cid,
            direction="inbound",
            sender_type="customer",
            body="👍",
            content_type="reaction",
            channel_message_id="wamid.REACT",
            status="received",
        )
    )
    await db.flush()
    ctx = await ctx_for(db, tenant_ctx, "owner")
    await send_read_signal(cid, ReadSignalRequest(), ctx=ctx)
    assert spy.calls[0][0] == "wamid.REAL"


@pytest.mark.asyncio
async def test_the_route_demands_write_and_a_viewer_is_refused(db, tenant_ctx) -> None:
    """Calling the function skips the route's gate, so test the gate itself: the route
    must depend on conversations:write, that dependency must refuse a viewer and let an
    owner through. Otherwise a viewer could make the business appear to have read."""
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/read-signal"))
    assert "POST" in route.methods
    gates = [d.call for d in route.dependant.dependencies if hasattr(d.call, "code")]
    assert [g.code for g in gates] == ["conversations:write"]

    viewer = await ctx_for(db, tenant_ctx, "viewer")
    owner = await ctx_for(db, tenant_ctx, "owner")
    with pytest.raises(PermissionDeniedError):
        await gates[0](viewer)
    assert await gates[0](owner) is owner
