"""A WhatsApp reply must stay linked to its quote, and reactions must fold in.

WhatsApp names a reply or reaction target by ITS id (a wamid), never by our UUID.
The ingest used to parse that as a UUID, fail, and store NULL, so every quoted
reply lost its link silently, and the messages API never returned the field
anyway. These tests drive the real adapter and ingest on a real database.
"""

from __future__ import annotations

import itertools
import uuid

import sqlalchemy as sa

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.modules.conversations.models import Message
from app.modules.conversations.routers.inbox import _present_messages
from app.modules.conversations.service import ConversationService

adapter = WhatsAppAdapter()
# WhatsApp stamps each event with epoch seconds; a later event has a larger one.
_CLOCK = itertools.count(1_700_000_000)


def _payload(wa_id: str, msg: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id, "profile": {"name": "Sara"}}],
                            "messages": [{"from": wa_id, "timestamp": str(next(_CLOCK)), **msg}],
                        }
                    }
                ]
            }
        ]
    }


async def _receive(db, tenant_id, wa_id: str, msg: dict) -> uuid.UUID:
    (inbound,) = adapter.parse_inbound(_payload(wa_id, msg))
    conversation_id = await IngestService.ingest(
        db, tenant_id=tenant_id, message=inbound, idempotency_scope="webhook:whatsapp"
    )
    assert conversation_id is not None
    return conversation_id


async def _rows(db, conversation_id):
    """Messages in the order they ARRIVED.

    Everything inserted inside one test transaction shares one database
    timestamp, so created_at cannot order them. WhatsApp's own event time (the
    strictly increasing `timestamp` each fake webhook carries) can.
    """
    result = await db.execute(sa.select(Message).where(Message.conversation_id == conversation_id))
    return sorted(result.scalars(), key=lambda m: int(m.payload["raw"]["timestamp"]))


async def test_a_quoted_reply_keeps_its_link_to_the_quoted_message(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    first = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db, tenant_ctx.tenant_id, wa, {"id": first, "type": "text", "text": {"body": "السعر؟"}}
    )
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        wa,
        {
            "id": f"wamid.{uuid.uuid4().hex}",
            "type": "text",
            "text": {"body": "وعايز لون أحمر"},
            "context": {"id": first},
        },
    )

    original, reply = await _rows(db, conversation_id)
    assert reply.reply_to_message_id == original.id
    assert reply.provider_metadata["reply_to_provider_id"] == first

    shown = _present_messages([original, reply], {})
    assert shown[1]["reply_to"] == {
        "id": str(original.id),
        "available": True,
        "direction": "inbound",
        "content_type": "text",
        "body": "السعر؟",
    }
    assert shown[0]["reply_to"] is None


async def test_a_reply_to_a_message_we_never_stored_is_marked_unavailable(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        wa,
        {
            "id": f"wamid.{uuid.uuid4().hex}",
            "type": "text",
            "text": {"body": "ده ردي"},
            "context": {"id": "wamid.never-stored"},
        },
    )
    (reply,) = await _rows(db, conversation_id)
    assert reply.reply_to_message_id is None
    assert _present_messages([reply], {})[0]["reply_to"] == {"id": None, "available": False}


async def test_a_reply_cannot_link_to_another_customers_message(db, tenant_ctx) -> None:
    """A forged context id naming a different conversation must not resolve."""
    victim_wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    victim_wamid = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db,
        tenant_ctx.tenant_id,
        victim_wa,
        {"id": victim_wamid, "type": "text", "text": {"body": "سري"}},
    )
    attacker_wa = f"2011{uuid.uuid4().int % 10**8:08d}"
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        attacker_wa,
        {
            "id": f"wamid.{uuid.uuid4().hex}",
            "type": "text",
            "text": {"body": "x"},
            "context": {"id": victim_wamid},
        },
    )
    (reply,) = await _rows(db, conversation_id)
    assert reply.reply_to_message_id is None


async def test_a_reaction_is_folded_into_its_target_and_not_listed(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    target = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db, tenant_ctx.tenant_id, wa, {"id": target, "type": "text", "text": {"body": "تم الشحن"}}
    )
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        wa,
        {
            "id": f"wamid.{uuid.uuid4().hex}",
            "type": "reaction",
            "reaction": {"message_id": target, "emoji": "👍"},
        },
    )
    rows = await _rows(db, conversation_id)
    assert [r.content_type for r in rows] == ["text", "reaction"]

    shown = _present_messages(rows, {})
    assert len(shown) == 1, "the reaction row must not appear as its own line"
    assert shown[0]["reactions"] == ["👍"]


async def test_a_changed_reaction_keeps_only_the_newest(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    target = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db, tenant_ctx.tenant_id, wa, {"id": target, "type": "text", "text": {"body": "تم"}}
    )
    for emoji in ("👍", "❤️"):
        conversation_id = await _receive(
            db,
            tenant_ctx.tenant_id,
            wa,
            {
                "id": f"wamid.{uuid.uuid4().hex}",
                "type": "reaction",
                "reaction": {"message_id": target, "emoji": emoji},
            },
        )
    assert _present_messages(await _rows(db, conversation_id), {})[0]["reactions"] == ["❤️"]


async def test_a_removed_reaction_leaves_nothing(db, tenant_ctx) -> None:
    """WhatsApp removes a reaction by sending an empty emoji."""
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    target = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db, tenant_ctx.tenant_id, wa, {"id": target, "type": "text", "text": {"body": "تم"}}
    )
    for emoji in ("👍", ""):
        conversation_id = await _receive(
            db,
            tenant_ctx.tenant_id,
            wa,
            {
                "id": f"wamid.{uuid.uuid4().hex}",
                "type": "reaction",
                "reaction": {"message_id": target, "emoji": emoji},
            },
        )
    assert _present_messages(await _rows(db, conversation_id), {})[0]["reactions"] == []


async def test_a_deleted_message_hides_its_text_and_media(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        wa,
        {"id": f"wamid.{uuid.uuid4().hex}", "type": "text", "text": {"body": "رقمي السري"}},
    )
    (message,) = await _rows(db, conversation_id)
    message.deleted = True
    shown = _present_messages([message], {})[0]
    assert shown["deleted"] is True
    assert shown["body"] is None and shown["media_url"] is None


async def test_a_quote_outside_the_page_is_fetched_not_called_unavailable(db, tenant_ctx) -> None:
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    old = f"wamid.{uuid.uuid4().hex}"
    await _receive(
        db, tenant_ctx.tenant_id, wa, {"id": old, "type": "text", "text": {"body": "رسالة قديمة"}}
    )
    conversation_id = await _receive(
        db,
        tenant_ctx.tenant_id,
        wa,
        {
            "id": f"wamid.{uuid.uuid4().hex}",
            "type": "text",
            "text": {"body": "رد"},
            "context": {"id": old},
        },
    )
    original, reply = await _rows(db, conversation_id)
    outside = await ConversationService.quoted_targets(
        db, tenant_ctx.tenant_id, conversation_id, [reply.reply_to_message_id]
    )
    quote = _present_messages([reply], {}, outside)[0]["reply_to"]
    assert quote["available"] is True and quote["body"] == "رسالة قديمة"
