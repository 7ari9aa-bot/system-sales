"""§33-34 inbound media ingest — fetch, screen, persist, link.

Channel media URLs EXPIRE within hours (WhatsApp especially), so the only
reliable moment to capture the bytes is message ingest. This module turns an
inbound message's `media_url` into a durable `Attachment` row that points at
our own storage, not at the provider's soon-dead URL.

Where it runs
-------------
Synchronously, from `ConversationService.add_message` — the single choke point
every inbound message already passes through (it enforces the §30-31 channel
policy and the §173 guardrail there). Two reasons:

* A worker hook would be a second, easily-forgotten ingress path. `add_message`
  is the one door; putting it here means a future producer cannot bypass it.
* The provider URL is only known at ingest. Deferring to a worker means hoping
  the worker runs before the URL expires — which is exactly the failure this
  module exists to prevent.

The trade-off is real and recorded: the fetch happens inside the caller's
transaction. It is bounded (30s timeout, `MAX_MEDIA_BYTES` streamed cap) and a
failure never rolls back the message. When a media worker lands, the call
should move there; the pipeline below is already a standalone, idempotent
method so that move is a one-line change.

What this deliberately does NOT do (§35 + the scanner, both deferred)
--------------------------------------------------------------------
* No AV / content scanning — a successful capture is left at
  `scan_status="stored"`, never "scanned", for a scanner that does not exist
  yet.
* No transcoding or thumbnailing — `processing_status` stays "pending".
* No speech-to-text — `transcription_status` stays NULL.

The gap this leaves: we trust the provider's declared Content-Type. There is
no magic-byte / MIME sniffing, so a file labelled `image/png` is stored and
later served as `image/png` even if its bytes are something else. Content-type
and size screening below is defence against obviously-hostile *inputs*, not a
substitute for the scanner.

Failure policy
--------------
Capturing media is a BONUS on top of the message, so no media failure may ever
cost the message. Every failure mode — policy refusal, provider fetch error, or
an unexpected error out of the storage client (boto3/botocore, a missing
optional dependency, a socket error) — is contained here: the Attachment is
recorded `scan_status="failed"` and the error is logged. The exception never
escapes to roll back `add_message`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.storage import (
    MAX_MEDIA_BYTES,
    FetchedMedia,
    StoredMedia,
    get_storage,
)
from app.modules.conversations.models import Attachment, Message

logger = logging.getLogger(__name__)


class MediaStorage(Protocol):
    """The slice of the storage port this pipeline needs (injectable in tests)."""

    async def fetch(
        self, url: str, *, max_bytes: int | None = MAX_MEDIA_BYTES
    ) -> FetchedMedia: ...

    async def store(
        self,
        media: FetchedMedia,
        *,
        prefix: str = "media",
        original_url: str | None = None,
    ) -> StoredMedia: ...


class MediaPolicyError(ValidationError):
    """Inbound media refused by policy (type or size)."""

    code = "media_policy_rejected"
    default_message = "inbound media rejected by policy"


# The FULL media type is allow-listed, never just its top-level `image/`
# family. A prefix rule admitted `image/svg` (an SVG without the `+xml`
# suffix), which renders and executes in a browser exactly like
# `image/svg+xml` — matching on the complete type closes that by construction,
# so an unknown subtype is refused instead of inheriting its family's trust.
ALLOWED_MEDIA_TYPES = frozenset(
    {
        # images
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "image/heic",
        "image/heif",
        # audio
        "audio/aac",
        "audio/amr",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
        "audio/webm",
        "audio/3gpp",
        # video
        "video/mp4",
        "video/3gpp",
        "video/quicktime",
        "video/webm",
        "video/mpeg",
        "video/x-msvideo",
        # documents
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
# Active content, called out explicitly even though the allow-list above
# already refuses it. Kept so the rejection reason is auditable at a glance:
# HTML/SVG/JS execute in a browser when an attachment is rendered inline, and
# executables run on a desktop. `application/octet-stream` is denied because a
# generic binary cannot be validated without the deferred scanner — refusing it
# is the fail-closed choice.
BLOCKED_MEDIA_TYPES = frozenset(
    {
        "image/svg+xml",
        "image/svg",
        "text/html",
        "application/xhtml+xml",
        "application/javascript",
        "text/javascript",
        "application/x-msdownload",
        "application/x-sh",
        "application/x-executable",
        "application/octet-stream",
    }
)


def normalize_mime(content_type: str | None) -> str:
    """Lower-case the media type and drop any parameters (`; charset=...`)."""
    return (content_type or "").split(";")[0].strip().lower()


def check_media_policy(*, content_type: str | None, size: int | None) -> str:
    """Refuse obviously unsafe inbound media; return the normalized MIME type.

    Pure and total: raises `MediaPolicyError` with a machine-readable `reason`
    so the rejection is explainable rather than a silent drop.
    """
    mime = normalize_mime(content_type)
    if not mime:
        raise MediaPolicyError(
            "inbound media has no content type",
            details={"reason": "missing_content_type"},
        )
    if mime in BLOCKED_MEDIA_TYPES:
        raise MediaPolicyError(
            f"content type {mime!r} is not accepted",
            details={"reason": "blocked_content_type", "content_type": mime},
        )
    if mime not in ALLOWED_MEDIA_TYPES:
        raise MediaPolicyError(
            f"content type {mime!r} is not accepted",
            details={"reason": "unsupported_content_type", "content_type": mime},
        )
    if size is not None and size > MAX_MEDIA_BYTES:
        raise MediaPolicyError(
            "inbound media exceeds the size limit",
            details={"reason": "too_large", "size": size, "max_bytes": MAX_MEDIA_BYTES},
        )
    return mime


class MediaService:
    """Attachment rows for inbound channel media."""

    @staticmethod
    async def ingest_inbound_media(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        message: Message,
        media_url: str,
        declared_media_type: str | None = None,
        storage: MediaStorage | None = None,
    ) -> Attachment | None:
        """Persist `media_url` and link the resulting Attachment to `message`.

        Idempotent for at-least-once redelivery: an Attachment that already
        succeeded is returned untouched and the provider is not fetched again.
        A previously FAILED attachment is retried, because a transient fetch
        error must be recoverable.

        Failure policy — media is a bonus, the message is not. A policy
        refusal, a provider fetch error, or ANY unexpected error out of the
        storage client (boto3/botocore `ClientError`, a missing optional
        dependency, a socket error) is contained here: the Attachment is
        recorded `scan_status="failed"` and the error is logged with a
        traceback. Nothing in this method lets a media failure propagate to
        `add_message` and roll back the customer's message.
        """
        if not media_url:
            return None
        storage = storage or get_storage()

        attachment = (
            await session.execute(
                select(Attachment)
                .where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.message_id == message.id,
                )
                .order_by(Attachment.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if attachment is not None and attachment.scan_status != "failed":
            return attachment

        if attachment is None:
            attachment = Attachment(
                tenant_id=tenant_id,
                message_id=message.id,
                conversation_id=message.conversation_id,
                workspace_id=message.workspace_id,
                location_id=message.location_id,
            )
            session.add(attachment)

        # The provider URL is recorded regardless of outcome: it is the only
        # evidence of what the customer actually sent.
        attachment.provider_url = media_url

        try:
            fetched = await storage.fetch(media_url, max_bytes=MAX_MEDIA_BYTES)
            mime = check_media_policy(
                content_type=fetched.content_type, size=len(fetched.data)
            )
            stored = await storage.store(
                fetched, prefix="media", original_url=media_url
            )
        except ValidationError as exc:
            # Refused by the size cap in the port, or by policy here.
            logger.warning(
                "media.rejected tenant=%s message=%s url=%s reason=%s",
                tenant_id,
                message.id,
                media_url,
                exc.message,
            )
            return await MediaService._mark_failed(
                session, attachment, declared_media_type
            )
        except Exception as exc:
            # EVERY other storage failure — httpx transport/status errors,
            # boto3/botocore ClientError, a missing boto3, an OSError from the
            # thread pool. Deliberately broad: the message is already durable
            # and must never be rolled back because a BONUS attachment could
            # not be stored. `logger.exception` keeps it loud (full traceback),
            # so this is contained, never silent. `CancelledError` is a
            # BaseException and still propagates.
            logger.exception(
                "media.ingest_failed tenant=%s message=%s url=%s error=%s: %s",
                tenant_id,
                message.id,
                media_url,
                type(exc).__name__,
                exc,
            )
            return await MediaService._mark_failed(
                session, attachment, declared_media_type
            )

        attachment.storage_key = stored.storage_key
        attachment.mime_type = mime
        # The fetched length, not `stored.bytes_written`: the port reports 0
        # for a pass-through, and the row should still record the real size.
        attachment.size = len(fetched.data)
        attachment.checksum = stored.checksum
        if stored.durable:
            # §33-34: the bytes are durable. The deferred scanner moves this to
            # "scanned"; the deferred transcoder moves processing to "ready".
            attachment.scan_status = "stored"
            attachment.processing_status = "pending"
            if mime.startswith("audio/"):
                # §35: a durable audio object IS a transcription job. This is the
                # only thing that ever queues one — VoiceService has no other
                # trigger, and without this a voice note is never transcribed.
                attachment.transcription_status = "pending"
        else:
            # S3 is not configured, so the object was NOT persisted durably and
            # only the expiring provider URL remains. That contradicts §33-34
            # ("provider URLs are never the source of truth"), so it is recorded
            # as a failure rather than a success with a lying status.
            logger.error(
                "media.not_durable tenant=%s message=%s url=%s — storage not configured",
                tenant_id,
                message.id,
                media_url,
            )
            attachment.scan_status = "failed"
            attachment.processing_status = "failed"
        await session.flush()
        return attachment

    @staticmethod
    async def _mark_failed(
        session: AsyncSession,
        attachment: Attachment,
        declared_media_type: str | None,
    ) -> Attachment:
        attachment.scan_status = "failed"
        attachment.processing_status = "failed"
        # Best-effort record of what the provider CLAIMED, for triage only —
        # never trusted as the stored type.
        attachment.mime_type = normalize_mime(declared_media_type) or None
        await session.flush()
        return attachment

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: uuid.UUID, attachment_id: uuid.UUID
    ) -> Attachment:
        """Tenant-scoped read; a foreign tenant's attachment is not found."""
        attachment = (
            await session.execute(
                select(Attachment).where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.id == attachment_id,
                )
            )
        ).scalar_one_or_none()
        if attachment is None:
            raise NotFoundError("attachment not found")
        return attachment

    @staticmethod
    async def list_for_message(
        session: AsyncSession, tenant_id: uuid.UUID, message_id: uuid.UUID
    ) -> list[Attachment]:
        """Tenant-scoped attachments for one message, oldest first."""
        rows = (
            await session.execute(
                select(Attachment)
                .where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.message_id == message_id,
                )
                .order_by(Attachment.created_at.asc())
            )
        ).scalars()
        return list(rows)


__all__ = [
    "ALLOWED_MEDIA_TYPES",
    "BLOCKED_MEDIA_TYPES",
    "MediaPolicyError",
    "MediaService",
    "MediaStorage",
    "check_media_policy",
    "normalize_mime",
]
