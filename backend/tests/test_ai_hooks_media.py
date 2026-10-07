"""Hook media delivery tests (spec §13) — photos ride AFTER the text reply.

Pins: one outbound message per image with ONE outbox event each, the
sent_media ledger created/appended with a state_version bump, the no-resend
rule (a photo already in sent_media is never delivered again), and no state
row at all when the run collected no media.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, ConversationAgentState
from app.modules.ai.runtime import AgentRunner, AgentRunResult
from app.modules.conversations import models as conv_models
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.platform.models import OutboxEvent

IMAGE_ID = "11111111-1111-1111-1111-111111111111"


def _media() -> list[dict]:
    return [
        {
            "image_id": IMAGE_ID,
            "image_url": "https://signed.test/a.png",
            "alt": "abaya كحلي",
        }
    ]


async def _seed(db, tenant_id):
    db.add(Agent(tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="s"))
    customer = Customer(tenant_id=tenant_id, name="Media Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="وريني المنتج",
    )
    await db.flush()
    return conversation


def _patch_runner(monkeypatch, media: list[dict], shown: list[str]) -> None:
    async def fake_run(self, session, tenant_id, **kwargs):
        return AgentRunResult(
            content="اتفضل صورة المنتج",
            guardrail_decision="allow",
            media=media,
            shown_product_ids=shown,
        )

    monkeypatch.setattr(AgentRunner, "run", fake_run)


async def _outbound(db, tenant_id, conversation_id) -> list:
    rows = (
        (
            await db.execute(
                select(conv_models.Message).where(
                    conv_models.Message.tenant_id == tenant_id,
                    conv_models.Message.conversation_id == conversation_id,
                    conv_models.Message.direction == "outbound",
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _state(db, tenant_id, conversation_id) -> ConversationAgentState | None:
    return (
        await db.execute(
            select(ConversationAgentState).where(
                ConversationAgentState.tenant_id == tenant_id,
                ConversationAgentState.conversation_id == conversation_id,
            )
        )
    ).scalar_one_or_none()


async def test_media_delivered_after_text_with_outbox_and_state(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    product_id = str(uuid.uuid4())
    conversation = await _seed(db, tenant_id)
    _patch_runner(monkeypatch, media=_media(), shown=[product_id])

    await maybe_auto_reply(db, tenant_id, conversation.id)

    outbound = await _outbound(db, tenant_id, conversation.id)
    assert [m.content_type for m in outbound] == ["text", "image"]
    image_message = outbound[1]
    assert image_message.media_type == "image"
    assert image_message.media_url == "https://signed.test/a.png"
    assert image_message.body is None

    events = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id.in_([str(m.id) for m in outbound])
                )
            )
        )
        .scalars()
        .all()
    )
    # ONE event per delivered message — text and image alike — each routed
    # as message.outbound and stamped with the tenant in the envelope meta.
    assert {str(event.aggregate_id) for event in events} == {str(m.id) for m in outbound}
    for event in events:
        assert event.payload["event_type"] == "message.outbound"
        assert str(event.meta["tenant_id"]) == str(tenant_id)

    state = await _state(db, tenant_id, conversation.id)
    assert state is not None
    assert state.sent_media == [IMAGE_ID]
    assert state.shown_items == [product_id]
    assert state.state_version == 1


async def test_no_resend_same_image_never_delivered_twice(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _seed(db, tenant_id)
    _patch_runner(monkeypatch, media=_media(), shown=[])

    await maybe_auto_reply(db, tenant_id, conversation.id)
    await maybe_auto_reply(db, tenant_id, conversation.id)

    outbound = await _outbound(db, tenant_id, conversation.id)
    image_messages = [m for m in outbound if m.content_type == "image"]
    assert len(image_messages) == 1, "the no-resend rule (§13)"

    state = await _state(db, tenant_id, conversation.id)
    assert state is not None
    assert state.sent_media == [IMAGE_ID]
    # Nothing new was sent, so the optimistic-concurrency version stays put.
    assert state.state_version == 1


async def test_new_image_appends_and_bumps_state_version(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _seed(db, tenant_id)
    _patch_runner(monkeypatch, media=_media(), shown=[])

    await maybe_auto_reply(db, tenant_id, conversation.id)
    _patch_runner(
        monkeypatch,
        media=[
            {
                "image_id": "22222222-2222-2222-2222-222222222222",
                "image_url": "https://signed.test/b.png",
                "alt": "من الخلف",
            }
        ],
        shown=[],
    )
    await maybe_auto_reply(db, tenant_id, conversation.id)

    state = await _state(db, tenant_id, conversation.id)
    assert state.sent_media == [IMAGE_ID, "22222222-2222-2222-2222-222222222222"]
    assert state.state_version == 2
    outbound = await _outbound(db, tenant_id, conversation.id)
    image_messages = [m for m in outbound if m.content_type == "image"]
    assert [m.media_url for m in image_messages] == [
        "https://signed.test/a.png",
        "https://signed.test/b.png",
    ]


async def test_no_media_no_state_row(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _seed(db, tenant_id)
    _patch_runner(monkeypatch, media=[], shown=[])

    await maybe_auto_reply(db, tenant_id, conversation.id)

    outbound = await _outbound(db, tenant_id, conversation.id)
    assert [m.content_type for m in outbound] == ["text"]
    assert await _state(db, tenant_id, conversation.id) is None
