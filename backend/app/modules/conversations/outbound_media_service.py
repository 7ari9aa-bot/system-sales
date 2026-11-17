"""Store an agent's upload and attach it to the message that sends it."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, StorageUnavailableError, ValidationError
from app.core.storage import FetchedMedia, get_storage
from app.modules.conversations.models import Attachment, Message
from app.modules.conversations.outbound_media import OutboundMediaSpec

logger = logging.getLogger(__name__)

# An upload nobody sends within this long is abandoned; it can no longer be sent.
UPLOAD_TTL = timedelta(hours=24)

# What a customer's WhatsApp is shown / asked to fetch. Meta downloads the file
# from this link once, right after we post the message, so minutes are enough;
# an hour covers a retry.
SEND_LINK_TTL_SECONDS = 60 * 60


class OutboundMediaService:
    @staticmethod
    async def store_upload(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID,
        spec: OutboundMediaSpec,
        data: bytes,
    ) -> Attachment:
        """Persist the bytes durably and record an Attachment not yet tied to a message."""
        storage = get_storage()
        if not storage.configured:
            raise StorageUnavailableError()
        stored = await storage.store(
            FetchedMedia(
                data=data, content_type=spec.mime, checksum=hashlib.sha256(data).hexdigest()
            ),
            prefix=f"outbound-media/{tenant_id}",
            original_url="",
        )
        if not stored.durable or not stored.storage_key:
            raise StorageUnavailableError()
        attachment = Attachment(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=None,
            storage_key=stored.storage_key,
            mime_type=spec.mime,
            size=spec.size,
            checksum=stored.checksum,
            # We produced this file; nothing external interprets it. The malware
            # scan is for customer-supplied media, an agent's own upload is not.
            scan_status="stored",
            processing_status="ready",
            kind=spec.kind,
            filename=spec.filename,
        )
        session.add(attachment)
        await session.flush()
        return attachment

    @staticmethod
    async def claim(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        media_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Attachment:
        """The upload a send request names, only if it may be sent here, now, once.

        It must belong to this tenant AND this conversation (an id from another
        customer's chat is reported as not found, never as "exists elsewhere"),
        must not already be attached to a message, and must be recent.
        """
        attachment = (
            await session.execute(
                select(Attachment)
                .where(Attachment.tenant_id == tenant_id, Attachment.id == media_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            attachment is None
            or attachment.conversation_id != conversation_id
            or not attachment.storage_key
            or not attachment.storage_key.startswith(f"outbound-media/{tenant_id}/")
        ):
            raise NotFoundError("uploaded file not found")
        if attachment.message_id is not None:
            raise ValidationError(
                "this file was already sent", details={"reason": "media_already_sent"}
            )
        if attachment.created_at < datetime.now(UTC) - UPLOAD_TTL:
            raise ValidationError(
                "this upload expired, upload the file again", details={"reason": "media_expired"}
            )
        return attachment

    @staticmethod
    async def attach(session: AsyncSession, attachment: Attachment, message: Message) -> None:
        attachment.message_id = message.id
        await session.flush()

    @staticmethod
    def link_for_provider(storage_key: str) -> str:
        """A fresh read link for the provider to download from at send time."""
        return get_storage().signed_url(storage_key, expires_in=SEND_LINK_TTL_SECONDS)
