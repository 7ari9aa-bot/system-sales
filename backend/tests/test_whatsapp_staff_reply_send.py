"""A staff reply that quotes a message must reach WhatsApp as a quoted reply.

The inbox used to have no way to say WHICH message a reply answers: the send
request had no field for it, so quoting existed only for what customers sent us.
These tests cover each hop: the payload, the worker that resolves our UUID to
the provider id, and the guard that keeps a quote inside its own conversation.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.conversations.gateway.base import OutboundMessage
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import REACTION_REMOVED, WhatsAppAdapter
from app.modules.conversations.models import Message
from app.modules.conversations.routers._deps import ReactionRequest, SendMessageRequest
from app.modules.conversations.routers.inbox import (
    _present_messages,
    react_to_message,
    send_message,
)
from app.modules.conversations.service import ConversationService
from app.workers.message_worker import MessageWorker, PermanentError
from tests._pos_helpers import ctx_for

adapter = WhatsAppAdapter()


def _outbound(**kw) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201001234567",
        **kw,
    )


# ---- the payload ---------------------------------------------------------------


def test_a_quoted_text_reply_carries_the_context_block() -> None:
    payload = adapter._build_send_payload(
        _outbound(body="تمام", meta={"reply_to_provider_id": "wamid.ABC"})
    )
    assert payload["type"] == "text"
    assert payload["context"] == {"message_id": "wamid.ABC"}


def test_a_quoted_media_reply_carries_the_context_block() -> None:
    payload = adapter._build_send_payload(
        _outbound(
            body="الصورة",
            media_url="https://cdn.example/x.jpg",
            meta={"media_type": "image", "reply_to_provider_id": "wamid.ABC"},
        )
    )
    assert payload["type"] == "image"
    assert payload["context"] == {"message_id": "wamid.ABC"}


def test_a_plain_message_has_no_context_block() -> None:
    payload = adapter._build_send_payload(_outbound(body="أهلا"))
    assert "context" not in payload


def test_a_template_is_never_sent_as_a_reply() -> None:
    payload = adapter._build_send_payload(
        _outbound(template_name="order_ready", meta={"reply_to_provider_id": "wamid.ABC"})
    )
    assert payload["type"] == "template"
    assert "context" not in payload


# ---- the route and the worker, on a real database -----------------------------------


async def _customer_message(db, tenant_id, wa: str, wamid: str, text: str) -> uuid.UUID:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa, "profile": {"name": "Sara"}}],
                            "messages": [
                                {
                                    "from": wa,
                                    "id": wamid,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    (inbound,) = adapter.parse_inbound(payload)
    conversation_id = await IngestService.ingest(
        db, tenant_id=tenant_id, message=inbound, idempotency_scope="webhook:whatsapp"
    )
    assert conversation_id is not None
    return conversation_id


async def _stored(db, conversation_id, wamid: str) -> Message:
    return (
        await db.execute(
            sa.select(Message).where(
                Message.conversation_id == conversation_id, Message.channel_message_id == wamid
            )
        )
    ).scalar_one()


async def test_the_worker_hands_the_provider_the_quoted_messages_own_id(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    wamid = f"wamid.{uuid.uuid4().hex}"
    conversation_id = await _customer_message(db, tenant_ctx.tenant_id, wa, wamid, "السعر؟")
    quoted = await _stored(db, conversation_id, wamid)

    reply = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body="٣٥٠ جنيه",
        reply_to_message_id=quoted.id,
    )
    plan = await MessageWorker(bus=MagicMock())._deliver_one(db, tenant_ctx.tenant_id, reply.id)

    assert plan is not None
    assert plan.outbound.meta["reply_to_provider_id"] == wamid
    assert adapter._build_send_payload(plan.outbound)["context"] == {"message_id": wamid}


async def test_a_message_that_quotes_nothing_sends_no_context(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    conversation_id = await _customer_message(
        db, tenant_ctx.tenant_id, wa, f"wamid.{uuid.uuid4().hex}", "مرحبا"
    )
    reply = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body="أهلا",
    )
    plan = await MessageWorker(bus=MagicMock())._deliver_one(db, tenant_ctx.tenant_id, reply.id)

    assert plan is not None
    assert "reply_to_provider_id" not in plan.outbound.meta
    assert "context" not in adapter._build_send_payload(plan.outbound)


async def test_the_route_refuses_to_quote_another_conversations_message(db, tenant_ctx) -> None:
    mine = await _customer_message(
        db,
        tenant_ctx.tenant_id,
        f"2010{uuid.uuid4().int % 10**8:08d}",
        f"wamid.{uuid.uuid4().hex}",
        "أنا",
    )
    other_wamid = f"wamid.{uuid.uuid4().hex}"
    other = await _customer_message(
        db, tenant_ctx.tenant_id, f"2011{uuid.uuid4().int % 10**8:08d}", other_wamid, "عميل تاني"
    )
    foreign = await _stored(db, other, other_wamid)

    with pytest.raises(NotFoundError):
        await send_message(
            mine,
            SendMessageRequest(body="رد", reply_to_message_id=foreign.id),
            ctx=await ctx_for(db, tenant_ctx, "owner"),
        )
    # Nothing was queued in either conversation.
    sent = (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(Message)
            .where(Message.direction == "outbound", Message.conversation_id.in_([mine, other]))
        )
    ).scalar_one()
    assert sent == 0


async def test_the_route_refuses_a_quote_that_does_not_exist(db, tenant_ctx) -> None:
    conversation_id = await _customer_message(
        db,
        tenant_ctx.tenant_id,
        f"2010{uuid.uuid4().int % 10**8:08d}",
        f"wamid.{uuid.uuid4().hex}",
        "مرحبا",
    )
    with pytest.raises(NotFoundError):
        await send_message(
            conversation_id,
            SendMessageRequest(body="رد", reply_to_message_id=uuid.uuid4()),
            ctx=await ctx_for(db, tenant_ctx, "owner"),
        )


async def test_the_worker_alone_also_refuses_to_quote_across_conversations(db, tenant_ctx) -> None:
    """Defence in depth: even if a row slipped past the route, the worker must not
    hand the provider another customer's message id."""
    mine = await _customer_message(
        db,
        tenant_ctx.tenant_id,
        f"2010{uuid.uuid4().int % 10**8:08d}",
        f"wamid.{uuid.uuid4().hex}",
        "أنا",
    )
    other_wamid = f"wamid.{uuid.uuid4().hex}"
    other = await _customer_message(
        db, tenant_ctx.tenant_id, f"2011{uuid.uuid4().int % 10**8:08d}", other_wamid, "عميل تاني"
    )
    foreign = await _stored(db, other, other_wamid)

    reply = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=mine,
        direction="outbound",
        sender_type="agent",
        body="رد",
        reply_to_message_id=foreign.id,
    )
    plan = await MessageWorker(bus=MagicMock())._deliver_one(db, tenant_ctx.tenant_id, reply.id)

    assert plan is not None
    assert "reply_to_provider_id" not in plan.outbound.meta
    assert "context" not in adapter._build_send_payload(plan.outbound)


# ---- reactions sent by staff ----------------------------------------------------


def test_a_reaction_is_sent_as_a_reaction_not_as_text() -> None:
    payload = adapter._build_send_payload(
        _outbound(body="👍", meta={"reaction_to_provider_id": "wamid.ABC"})
    )
    assert payload["type"] == "reaction"
    assert payload["reaction"] == {"message_id": "wamid.ABC", "emoji": "👍"}
    assert "text" not in payload and "context" not in payload


def test_withdrawing_a_reaction_sends_an_empty_emoji() -> None:
    payload = adapter._build_send_payload(
        _outbound(body=REACTION_REMOVED, meta={"reaction_to_provider_id": "wamid.ABC"})
    )
    assert payload["reaction"]["emoji"] == ""


async def _react(db, tenant_ctx, conversation_id, message_id, emoji):
    return await react_to_message(
        conversation_id,
        message_id,
        ReactionRequest(emoji=emoji),
        ctx=await ctx_for(db, tenant_ctx, "owner"),
    )


async def test_a_staff_reaction_is_queued_and_folds_onto_its_target(db, tenant_ctx) -> None:
    wamid = f"wamid.{uuid.uuid4().hex}"
    conversation_id = await _customer_message(
        db, tenant_ctx.tenant_id, f"2010{uuid.uuid4().int % 10**8:08d}", wamid, "السعر؟"
    )
    target = await _stored(db, conversation_id, wamid)

    out = await _react(db, tenant_ctx, conversation_id, target.id, "👍")
    assert out["emoji"] == "👍"

    rows = list(
        (await db.execute(sa.select(Message).where(Message.conversation_id == conversation_id)))
        .scalars()
        .all()
    )
    items = _present_messages(rows, {})
    # The reaction is not a line of its own: it sits on the message it answers.
    assert [i["id"] for i in items] == [str(target.id)]
    assert items[0]["reactions"] == ["👍"]
    assert items[0]["my_reaction"] == "👍"

    plan = await MessageWorker(bus=MagicMock())._deliver_one(
        db, tenant_ctx.tenant_id, uuid.UUID(out["id"])
    )
    assert plan is not None
    sent = adapter._build_send_payload(plan.outbound)
    assert sent["type"] == "reaction"
    assert sent["reaction"]["message_id"] == wamid


async def test_withdrawing_removes_it_from_the_target(db, tenant_ctx) -> None:
    wamid = f"wamid.{uuid.uuid4().hex}"
    conversation_id = await _customer_message(
        db, tenant_ctx.tenant_id, f"2010{uuid.uuid4().int % 10**8:08d}", wamid, "تمام"
    )
    target = await _stored(db, conversation_id, wamid)
    await _react(db, tenant_ctx, conversation_id, target.id, "❤️")
    await _react(db, tenant_ctx, conversation_id, target.id, "")

    rows = list(
        (await db.execute(sa.select(Message).where(Message.conversation_id == conversation_id)))
        .scalars()
        .all()
    )
    after = _present_messages(rows, {})[0]
    assert after["reactions"] == []
    assert after["my_reaction"] == ""


async def test_a_reaction_cannot_target_another_conversations_message(db, tenant_ctx) -> None:
    mine = await _customer_message(
        db,
        tenant_ctx.tenant_id,
        f"2010{uuid.uuid4().int % 10**8:08d}",
        f"wamid.{uuid.uuid4().hex}",
        "أنا",
    )
    other_wamid = f"wamid.{uuid.uuid4().hex}"
    other = await _customer_message(
        db, tenant_ctx.tenant_id, f"2011{uuid.uuid4().int % 10**8:08d}", other_wamid, "تاني"
    )
    foreign = await _stored(db, other, other_wamid)
    with pytest.raises(NotFoundError):
        await _react(db, tenant_ctx, mine, foreign.id, "👍")


async def test_a_reaction_to_a_reaction_or_a_deleted_message_is_refused(db, tenant_ctx) -> None:
    wamid = f"wamid.{uuid.uuid4().hex}"
    conversation_id = await _customer_message(
        db, tenant_ctx.tenant_id, f"2010{uuid.uuid4().int % 10**8:08d}", wamid, "x"
    )
    target = await _stored(db, conversation_id, wamid)
    target.deleted = True
    await db.flush()
    with pytest.raises(ConflictError):
        await _react(db, tenant_ctx, conversation_id, target.id, "👍")


@pytest.mark.parametrize("bad", ["hello", "a", "👍 👍", "1"])
async def test_only_an_emoji_is_accepted(db, tenant_ctx, bad) -> None:
    wamid = f"wamid.{uuid.uuid4().hex}"
    conversation_id = await _customer_message(
        db, tenant_ctx.tenant_id, f"2010{uuid.uuid4().int % 10**8:08d}", wamid, "x"
    )
    target = await _stored(db, conversation_id, wamid)
    with pytest.raises(ValidationError):
        await _react(db, tenant_ctx, conversation_id, target.id, bad)


async def test_the_worker_fails_a_reaction_whose_target_is_gone(db, tenant_ctx) -> None:
    """Never let it go out as a plain text message holding only an emoji."""
    conversation_id = await _customer_message(
        db,
        tenant_ctx.tenant_id,
        f"2010{uuid.uuid4().int % 10**8:08d}",
        f"wamid.{uuid.uuid4().hex}",
        "x",
    )
    orphan = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body="👍",
        content_type="reaction",
    )
    with pytest.raises(PermanentError):
        await MessageWorker(bus=MagicMock())._deliver_one(db, tenant_ctx.tenant_id, orphan.id)
