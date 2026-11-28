"""Sending a file to a customer: the payload Meta receives, the upload, and the worker.

Before this, the send API took only text, a template or a reply, and the worker
never told the adapter what KIND of file it was carrying, so every file would
have gone out as an image. These tests cover each hop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage
from app.applications.apparel.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.applications.apparel.modules.conversations.models import Attachment, Message
from app.applications.apparel.modules.conversations.routers._deps import SendMessageRequest
from app.applications.apparel.modules.conversations.routers.inbox import send_message
from app.workers.message_worker import MessageWorker, PermanentError
from tests._pos_helpers import ctx_for
from tests.test_whatsapp_staff_reply_send import _customer_message

adapter = WhatsAppAdapter()
URL = "https://files.example/signed?sig=abc"


def _outbound(**kw) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201001234567",
        **kw,
    )


# ---- the payload Meta receives (no database) -------------------------------------


def test_an_image_carries_its_caption_inside_the_media_object() -> None:
    p = adapter._build_send_payload(
        _outbound(body="طلبك", media_url=URL, meta={"media_type": "image"})
    )
    assert p["type"] == "image"
    assert p["image"] == {"link": URL, "caption": "طلبك"}
    assert "caption" not in p  # Meta ignores a caption placed beside the object


def test_a_document_carries_its_file_name_and_caption() -> None:
    p = adapter._build_send_payload(
        _outbound(
            body="الفاتورة",
            media_url=URL,
            meta={"media_type": "document", "filename": "Invoice.pdf"},
        )
    )
    assert p["type"] == "document"
    assert p["document"] == {"link": URL, "filename": "Invoice.pdf", "caption": "الفاتورة"}


def test_a_video_carries_its_caption() -> None:
    p = adapter._build_send_payload(
        _outbound(body="شوف", media_url=URL, meta={"media_type": "video"})
    )
    assert p["video"] == {"link": URL, "caption": "شوف"}


@pytest.mark.parametrize("kind", ["audio", "sticker"])
def test_audio_and_stickers_never_carry_a_caption(kind) -> None:
    # Meta rejects a caption on these, which would fail the whole send.
    p = adapter._build_send_payload(
        _outbound(body="ignored", media_url=URL, meta={"media_type": kind})
    )
    assert p["type"] == kind
    assert p[kind] == {"link": URL}


def test_media_without_a_caption_has_no_caption_key() -> None:
    p = adapter._build_send_payload(_outbound(media_url=URL, meta={"media_type": "image"}))
    assert p["image"] == {"link": URL}


def test_a_quoted_file_still_carries_the_context_block() -> None:
    p = adapter._build_send_payload(
        _outbound(media_url=URL, meta={"media_type": "document", "reply_to_provider_id": "wamid.A"})
    )
    assert p["context"] == {"message_id": "wamid.A"}


# ---- the request model ----------------------------------------------------------


def test_the_request_accepts_a_media_id() -> None:
    mid = uuid.uuid4()
    assert SendMessageRequest(media_id=mid, body="x").media_id == mid
    assert SendMessageRequest(body="x").media_id is None


# ---- the route and the worker, on a real database --------------------------------


class _FakeStorage:
    configured = True

    def __init__(self) -> None:
        self.stored: list[tuple[str, bytes]] = []

    async def store(self, media, *, prefix="media", original_url=None):
        from app.core.storage import StoredMedia

        key = f"{prefix}/{uuid.uuid4().hex}.bin"
        self.stored.append((key, media.data))
        return StoredMedia(
            url=f"https://bucket/{key}",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key=key,
            checksum=media.checksum,
        )

    def signed_url(self, key, *, expires_in=None):
        return f"https://signed.example/{key}?exp={expires_in}"


@pytest.fixture
def storage(monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr(
        "app.applications.apparel.modules.conversations.outbound_media_service.get_storage", lambda: fake
    )
    return fake


PDF = b"%PDF-1.7\n" + b"0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


async def _upload(
    db,
    tenant_id,
    conversation_id,
    storage,
    *,
    mime="application/pdf",
    data=PDF,
    name="Invoice.pdf",
    sticker=False,
):
    from app.applications.apparel.modules.conversations.outbound_media import check_outbound_media
    from app.applications.apparel.modules.conversations.outbound_media_service import OutboundMediaService

    spec = check_outbound_media(content_type=mime, data=data, filename=name, as_sticker=sticker)
    return await OutboundMediaService.store_upload(
        db, tenant_id, conversation_id=conversation_id, spec=spec, data=data
    )


async def _chat(db, tenant_ctx):
    wa = f"2010{uuid.uuid4().int % 10**8:08d}"
    return await _customer_message(
        db, tenant_ctx.tenant_id, wa, f"wamid.{uuid.uuid4().hex}", "أرسل الفاتورة"
    )


async def test_an_upload_is_stored_durably_and_not_yet_attached(db, tenant_ctx, storage) -> None:
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    assert att.message_id is None
    assert att.kind == "document" and att.filename == "Invoice.pdf"
    assert att.storage_key.startswith(f"outbound-media/{tenant_ctx.tenant_id}/")
    assert storage.stored[0][1] == PDF


async def test_sending_a_file_makes_a_message_of_the_right_kind(db, tenant_ctx, storage) -> None:
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    result = await send_message(cid, SendMessageRequest(media_id=att.id, body="الفاتورة"), ctx=ctx)
    msg = (
        await db.execute(sa.select(Message).where(Message.id == uuid.UUID(result["id"])))
    ).scalar_one()
    assert msg.content_type == "file" and msg.media_type == "document"
    assert msg.body == "الفاتورة"
    assert msg.media_url == f"s3://{att.storage_key}"
    assert msg.provider_metadata["filename"] == "Invoice.pdf"
    await db.refresh(att)
    assert att.message_id == msg.id


async def test_a_file_can_only_be_sent_once(db, tenant_ctx, storage) -> None:
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)
    with pytest.raises(ValidationError) as e:
        await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)
    assert e.value.details["reason"] == "media_already_sent"


async def test_another_conversations_upload_is_not_found(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    mine = await _chat(db, tenant_ctx)
    other = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, other, storage)
    with pytest.raises(NotFoundError):
        await send_message(mine, SendMessageRequest(media_id=att.id), ctx=ctx)


async def test_an_unknown_media_id_is_not_found(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    with pytest.raises(NotFoundError):
        await send_message(cid, SendMessageRequest(media_id=uuid.uuid4()), ctx=ctx)


async def test_an_old_upload_expires(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    await db.execute(
        sa.update(Attachment)
        .where(Attachment.id == att.id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await db.flush()
    with pytest.raises(ValidationError) as e:
        await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)
    assert e.value.details["reason"] == "media_expired"


async def test_a_caption_on_a_voice_note_is_refused(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(
        db,
        tenant_ctx.tenant_id,
        cid,
        storage,
        mime="audio/ogg",
        data=b"OggS" + b"0" * 32,
        name="v.ogg",
    )
    with pytest.raises(ValidationError) as e:
        await send_message(cid, SendMessageRequest(media_id=att.id, body="hello"), ctx=ctx)
    assert e.value.details["reason"] == "caption_not_allowed"


async def test_a_template_cannot_carry_a_file(db, tenant_ctx, storage) -> None:
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    with pytest.raises(ValidationError):
        await send_message(
            cid,
            SendMessageRequest(media_id=att.id, template_name="order_ready"),
            ctx=await ctx_for(db, tenant_ctx, "owner"),
        )


async def test_the_worker_signs_a_fresh_link_and_passes_the_kind_and_name(
    db, tenant_ctx, storage
) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    result = await send_message(cid, SendMessageRequest(media_id=att.id, body="الفاتورة"), ctx=ctx)
    plan = await MessageWorker(bus=MagicMock())._deliver_one(
        db, tenant_ctx.tenant_id, uuid.UUID(result["id"])
    )
    assert plan is not None
    assert plan.outbound.media_url.startswith("https://signed.example/outbound-media/")
    assert plan.outbound.meta["media_type"] == "document"
    assert plan.outbound.meta["filename"] == "Invoice.pdf"
    payload = adapter._build_send_payload(plan.outbound)
    assert payload["document"]["filename"] == "Invoice.pdf"
    assert payload["document"]["caption"] == "الفاتورة"


async def test_a_sticker_is_sent_as_a_sticker_without_a_caption(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(
        db,
        tenant_ctx.tenant_id,
        cid,
        storage,
        mime="image/webp",
        data=b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 32,
        name="s.webp",
        sticker=True,
    )
    result = await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)
    plan = await MessageWorker(bus=MagicMock())._deliver_one(
        db, tenant_ctx.tenant_id, uuid.UUID(result["id"])
    )
    payload = adapter._build_send_payload(plan.outbound)
    assert payload["type"] == "sticker" and set(payload["sticker"]) == {"link"}


async def test_a_file_the_storage_cannot_read_fails_the_message_permanently(
    db, tenant_ctx, storage, monkeypatch
) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    result = await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)

    def boom(*a, **k):
        raise RuntimeError("storage down")

    monkeypatch.setattr(storage, "signed_url", boom)
    with pytest.raises(PermanentError):
        await MessageWorker(bus=MagicMock())._deliver_one(
            db, tenant_ctx.tenant_id, uuid.UUID(result["id"])
        )


async def test_a_closed_conversation_refuses_a_file(db, tenant_ctx, storage) -> None:
    ctx = await ctx_for(db, tenant_ctx, "owner")
    cid = await _chat(db, tenant_ctx)
    att = await _upload(db, tenant_ctx.tenant_id, cid, storage)
    await db.execute(sa.text("UPDATE conversations SET status='closed' WHERE id=:i"), {"i": cid})
    await db.flush()
    with pytest.raises(ConflictError):
        await send_message(cid, SendMessageRequest(media_id=att.id), ctx=ctx)


# --- the message list tells the inbox what a sent file was called -------------


def _row(**kw):
    base = dict(
        id=uuid.uuid4(),
        direction="outbound",
        body=None,
        media_url=None,
        media_type="document",
        content_type="file",
        status="sent",
        edited=False,
        deleted=False,
        reply_to_message_id=None,
        provider_metadata={"filename": "فاتورة مايو.pdf"},
        created_at=datetime.now(UTC),
        sender_type="agent",
        provider_message_id=None,
        provider_timestamp=None,
    )
    base.update(kw)
    return MagicMock(**base)


def test_the_list_returns_the_name_a_document_was_sent_under() -> None:
    from app.applications.apparel.modules.conversations.routers.inbox import _present_messages

    [item] = _present_messages([_row()], {})
    assert item["filename"] == "فاتورة مايو.pdf"


def test_a_deleted_message_does_not_leak_its_file_name() -> None:
    from app.applications.apparel.modules.conversations.routers.inbox import _present_messages

    [item] = _present_messages([_row(deleted=True)], {})
    assert item["filename"] is None


def test_a_message_with_no_metadata_has_no_file_name() -> None:
    from app.applications.apparel.modules.conversations.routers.inbox import _present_messages

    [item] = _present_messages([_row(provider_metadata=None)], {})
    assert item["filename"] is None
