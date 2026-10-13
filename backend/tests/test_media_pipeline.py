"""§33-35 — inbound media pipeline: fetch, screen, persist, scan, link.

Three classes of test:

* DB-free guards for the pure policy function, the storage port's bounding
  and SSRF behaviour, and the clamd INSTREAM protocol client — these run
  everywhere.
* DB-backed tests for the Attachment rows: persistence, linkage, tenant
  isolation and at-least-once idempotency. They skip when no database URL is
  configured (the local default), and run in CI.
* Scanner-integration tests (ADR-062, amended): a fake clamd TCP server on
  loopback drives the real `ingest_inbound_media` through the verdict
  vocabulary — clean → scanned, infected → quarantined, outage/malformed →
  stays pending — and pins the fail-closed default (no scanner configured →
  the image stays pending and vision egress refuses it).

Transcoding/STT remain out of scope (§35 deferred): nothing here asserts a
"processed" state — the pipeline leaves `processing_status` at "pending" for
the future worker (the ADR-062 gap).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
import uuid
from contextlib import suppress
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.storage as storage_mod
import app.modules.conversations.media as media_mod
from app.core.errors import NotFoundError, ValidationError
from app.core.media_scanner import MediaScannerError
from app.core.media_scanner import scan as scan_bytes
from app.core.storage import MAX_MEDIA_BYTES, FetchedMedia, ObjectStorage, StoredMedia
from app.modules.conversations.media import (
    MediaPolicyError,
    MediaService,
    check_media_policy,
    normalize_mime,
)
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService

MEDIA_URL = "https://cdn.example.test/photo.jpg"
PAYLOAD = b"\xff\xd8\xff\xe0not-really-a-jpeg"


# --------------------------------------------------------------- fakes -----


class FakeStorage:
    """Stands in for the S3 port: no network, records what was asked of it."""

    def __init__(
        self,
        *,
        data: bytes = PAYLOAD,
        content_type: str | None = "image/jpeg",
        durable: bool = True,
        error: Exception | None = None,
        store_error: Exception | None = None,
    ) -> None:
        self.data = data
        self.content_type = content_type
        self.durable = durable
        self.error = error
        self.store_error = store_error
        self.fetch_calls = 0
        self.store_calls = 0

    async def fetch(self, url: str, *, max_bytes: int | None = MAX_MEDIA_BYTES) -> FetchedMedia:
        self.fetch_calls += 1
        if self.error is not None:
            raise self.error
        return FetchedMedia(
            data=self.data,
            content_type=self.content_type,
            checksum=hashlib.sha256(self.data).hexdigest(),
        )

    async def store(
        self,
        media: FetchedMedia,
        *,
        prefix: str = "media",
        original_url: str | None = None,
    ) -> StoredMedia:
        self.store_calls += 1
        if self.store_error is not None:
            raise self.store_error
        return StoredMedia(
            url="https://bucket.test/media/abc.jpg",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=self.durable,
            # Mirrors the real port: no durable object means no key.
            storage_key="media/abc.jpg" if self.durable else None,
            checksum=media.checksum,
        )


class StorageClientError(Exception):
    """Stand-in for botocore's ClientError.

    Deliberately neither a `ValidationError` nor an `httpx.HTTPError`: this is
    the exception class the pipeline used to let escape and roll back the
    customer's message.
    """


def _set_scanner(monkeypatch: pytest.MonkeyPatch, *, host: str = "", port: int = 0) -> None:
    """Point the pipeline's settings read at an explicit scanner config.

    `get_settings` is process-cached, so the ingest path (which reads it
    twice — the retry check and `_scan_image`) is patched here rather than
    fed environment variables: the SimpleNamespace carries exactly the three
    attributes the pipeline touches.
    """
    settings = SimpleNamespace(
        media_scanner_host=host,
        media_scanner_port=port,
        media_scanner_configured=bool(host.strip()) and port > 0,
    )
    monkeypatch.setattr(media_mod, "get_settings", lambda: settings)


class FakeClamd:
    """A loopback asyncio TCP server speaking clamd's INSTREAM dialect.

    Stands in for a real daemon the same way FakeStorage stands in for S3:
    no external network, and it records what it was handed. `reply` is the
    raw verdict line a daemon would send (`stream: OK`, or
    `stream: Eicar-Test-Signature FOUND` for the infected case, or garbage
    for the malformed case); `refuse=True` accepts the connection and closes
    it unread — the socket shape of a daemon that is down.
    """

    def __init__(self, *, reply: str = "stream: OK\n", refuse: bool = False) -> None:
        self.reply = reply
        self.refuse = refuse
        self.streams_seen = 0
        self.last_stream: bytes | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> FakeClamd:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            if self.refuse:
                return
            if await reader.readexactly(len(b"zINSTREAM\0")) != b"zINSTREAM\0":
                return
            stream = bytearray()
            while True:
                (length,) = struct.unpack("!I", await reader.readexactly(4))
                if length == 0:
                    break
                stream.extend(await reader.readexactly(length))
            self.streams_seen += 1
            self.last_stream = bytes(stream)
            writer.write(self.reply.encode())
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Point the port's own AsyncClient at a MockTransport.

    `ObjectStorage` constructs `httpx.AsyncClient` itself, so the class is
    swapped for a factory that injects the mock transport. The real class is
    captured first to avoid recursing into the patch.
    """
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(storage_mod.httpx, "AsyncClient", factory)


# ------------------------------------------------------- policy (pure) -----


@pytest.mark.parametrize(
    "content_type",
    [
        "image/jpeg",
        "image/png; charset=binary",
        "audio/ogg",
        "video/mp4",
        "application/pdf",
        "text/plain",
    ],
)
def test_common_media_types_are_allowed(content_type: str) -> None:
    assert check_media_policy(content_type=content_type, size=1024)


@pytest.mark.parametrize(
    "content_type",
    [
        "image/svg+xml",  # script-carrying image
        "image/svg",  # same thing without the +xml suffix
        "text/html",  # renders/executes inline
        "application/javascript",
        "application/xhtml+xml",
        "application/x-msdownload",
        "application/octet-stream",  # unvalidatable without the scanner
    ],
)
def test_active_content_is_refused(content_type: str) -> None:
    with pytest.raises(MediaPolicyError) as exc:
        check_media_policy(content_type=content_type, size=1024)
    assert exc.value.details["reason"] in {
        "blocked_content_type",
        "unsupported_content_type",
    }


@pytest.mark.parametrize(
    "content_type",
    [
        "image/svg",
        "image/svgz",
        "image/svg+xml; charset=utf-8",
        "audio/x-ms-wma",  # a real subtype we simply do not allow
        "video/x-matroska",
    ],
)
def test_an_unknown_subtype_does_not_inherit_its_family(content_type: str) -> None:
    """Allow-listing is on the FULL type — `image/...` is not a free pass."""
    with pytest.raises(MediaPolicyError) as exc:
        check_media_policy(content_type=content_type, size=1024)
    assert exc.value.details["reason"] in {
        "blocked_content_type",
        "unsupported_content_type",
    }


@pytest.mark.parametrize("content_type", [None, "", "   ", "garbage"])
def test_missing_or_malformed_content_type_is_refused(content_type) -> None:
    with pytest.raises(MediaPolicyError) as exc:
        check_media_policy(content_type=content_type, size=1024)
    assert exc.value.details["reason"] in {
        "missing_content_type",
        "unsupported_content_type",
    }


def test_oversized_media_is_refused() -> None:
    with pytest.raises(MediaPolicyError) as exc:
        check_media_policy(content_type="image/jpeg", size=MAX_MEDIA_BYTES + 1)
    assert exc.value.details["reason"] == "too_large"
    # At the limit is fine; only strictly larger is refused.
    assert check_media_policy(content_type="image/jpeg", size=MAX_MEDIA_BYTES)


def test_mime_is_normalized_before_matching() -> None:
    assert normalize_mime("Image/JPEG; charset=binary") == "image/jpeg"
    assert normalize_mime(None) == ""
    # A parameter cannot smuggle a denied type past the allow-list.
    with pytest.raises(MediaPolicyError):
        check_media_policy(content_type="text/html; charset=utf-8", size=1)


def test_refusal_is_a_validation_error_with_a_stable_code() -> None:
    err = MediaPolicyError("nope")
    assert isinstance(err, ValidationError)
    assert err.code == "media_policy_rejected"
    assert err.http_status == 400


# ---------------------------------------------------- storage port ---------


async def test_storage_refuses_an_oversized_body(monkeypatch) -> None:
    """The size cap is enforced on the stream, so the body is never buffered."""
    monkeypatch.setattr(storage_mod, "assert_public_url", lambda url: url)
    _patch_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"x" * 4096,
        ),
    )
    port = ObjectStorage()
    with pytest.raises(ValidationError):
        await port.fetch(MEDIA_URL, max_bytes=1024)


async def test_storage_refuses_an_oversized_stream_without_content_length(
    monkeypatch,
) -> None:
    """A hostile server can omit Content-Length; the streaming cap still holds."""

    async def chunks():
        yield b"x" * 2048
        yield b"y" * 2048

    monkeypatch.setattr(storage_mod, "assert_public_url", lambda url: url)
    _patch_httpx(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=chunks(),
        ),
    )
    port = ObjectStorage()
    with pytest.raises(ValidationError):
        await port.fetch(MEDIA_URL, max_bytes=1024)


async def test_storage_checks_every_redirect_hop(monkeypatch) -> None:
    """A 302 to a private address must not be followed (SSRF)."""
    seen: list[str] = []

    def guard(url: str) -> str:
        seen.append(url)
        if "169.254.169.254" in url:
            raise ValidationError("url host is not allowed")
        return url

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example.test":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, content=b"secret")

    monkeypatch.setattr(storage_mod, "assert_public_url", guard)
    _patch_httpx(monkeypatch, handler)
    port = ObjectStorage()
    with pytest.raises(ValidationError):
        await port.fetch(MEDIA_URL, max_bytes=1024)
    assert any("169.254.169.254" in url for url in seen)


def test_storage_extension_is_sanitized() -> None:
    port = ObjectStorage()
    assert port._extension("image/jpeg") == "jpeg"
    assert port._extension("image/jpeg; charset=binary") == "jpeg"
    assert port._extension("image/svg+xml") == "bin"
    assert port._extension("../../etc/passwd") == "bin"
    assert port._extension(None) == "bin"


# ------------------------------------------------------------- DB-backed ---


async def _conversation(db: AsyncSession, tenant_id: uuid.UUID):
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Media Tester"
    )
    return await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )


async def _inbound(db, tenant_id, conversation, storage, **overrides):
    params = {
        "conversation_id": conversation.id,
        "direction": "inbound",
        "sender_type": "customer",
        "media_url": MEDIA_URL,
        "media_type": "image",
        "channel_message_id": f"wamid-{uuid.uuid4().hex[:12]}",
        "media_storage": storage,
    }
    params.update(overrides)
    return await ConversationService.add_message(db, tenant_id, **params)


async def test_inbound_media_is_persisted_and_recorded(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage()
    _set_scanner(monkeypatch)  # pin the unconfigured default for determinism

    message = await _inbound(db, tenant_id, conversation, storage)

    assert storage.fetch_calls == 1
    assert storage.store_calls == 1
    attachments = await MediaService.list_for_message(db, tenant_id, message.id)
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment.provider_url == MEDIA_URL
    assert attachment.storage_key == "media/abc.jpg"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.size == len(PAYLOAD)
    assert attachment.checksum == hashlib.sha256(PAYLOAD).hexdigest()
    # Fail-closed default (ADR-062): no scanner configured, so the image can
    # never be marked "stored"-and-trusted — it stays pending and the vision
    # gate refuses it. Transcoding is the deferred worker's job.
    assert attachment.scan_status == "pending"
    assert attachment.processing_status == "pending"
    assert attachment.transcription_status is None


async def test_attachment_is_linked_to_its_message_and_tenant(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)

    message = await _inbound(db, tenant_id, conversation, FakeStorage())
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]

    assert attachment.tenant_id == tenant_id
    assert attachment.message_id == message.id
    assert attachment.conversation_id == conversation.id
    # The message still carries the original provider reference for the UI.
    assert message.media_url == MEDIA_URL


async def test_another_tenant_cannot_read_the_attachment(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _inbound(db, tenant_id, conversation, FakeStorage())
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]

    assert (await MediaService.get(db, tenant_id, attachment.id)).id == attachment.id
    with pytest.raises(NotFoundError):
        await MediaService.get(db, uuid.uuid4(), attachment.id)


async def test_redelivered_message_does_not_refetch_or_duplicate(db, tenant_ctx):
    """Workers are at-least-once: the second delivery must be a no-op."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage()
    channel_message_id = f"wamid-{uuid.uuid4().hex[:12]}"

    first = await _inbound(
        db, tenant_id, conversation, storage, channel_message_id=channel_message_id
    )
    second = await _inbound(
        db, tenant_id, conversation, storage, channel_message_id=channel_message_id
    )

    assert second.id == first.id
    assert storage.fetch_calls == 1
    assert storage.store_calls == 1
    assert len(await MediaService.list_for_message(db, tenant_id, first.id)) == 1


async def test_media_ingest_is_idempotent_at_the_media_layer(db, tenant_ctx, monkeypatch):
    """Pins the pipeline's OWN early return, not `add_message`'s message dedupe.

    Re-entering `ingest_inbound_media` directly — a path `add_message` would
    normally short-circuit before — must return the existing attachment without
    touching the provider or writing a second row.
    """
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    first_storage = FakeStorage()
    message = await _inbound(db, tenant_id, conversation, first_storage)
    assert first_storage.fetch_calls == 1
    _set_scanner(monkeypatch)  # pin the unconfigured default for determinism

    second_storage = FakeStorage()
    again = await MediaService.ingest_inbound_media(
        db, tenant_id, message=message, media_url=MEDIA_URL, storage=second_storage
    )

    assert again is not None
    assert again.scan_status == "pending"  # no scanner configured: untouched
    assert second_storage.fetch_calls == 0  # the provider was not contacted
    assert second_storage.store_calls == 0  # and nothing was re-written
    assert len(await MediaService.list_for_message(db, tenant_id, message.id)) == 1


async def test_disallowed_content_type_is_refused_before_storage(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(content_type="text/html")

    message = await _inbound(db, tenant_id, conversation, storage)
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]

    assert attachment.scan_status == "failed"
    assert attachment.processing_status == "failed"
    # Screened after fetching (the provider's declaration is untrusted) but
    # BEFORE anything was written to the bucket.
    assert storage.fetch_calls == 1
    assert storage.store_calls == 0


async def test_oversized_media_is_refused_and_not_stored(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(
        error=ValidationError(
            "media exceeds the size limit", details={"max_bytes": MAX_MEDIA_BYTES}
        )
    )

    message = await _inbound(db, tenant_id, conversation, storage)
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]

    assert attachment.scan_status == "failed"
    assert storage.store_calls == 0


async def test_provider_fetch_failure_is_recorded_not_swallowed(db, tenant_ctx, caplog):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(error=httpx.ConnectError("provider unreachable"))

    with caplog.at_level(logging.ERROR):
        message = await _inbound(db, tenant_id, conversation, storage)

    # The message survives — the customer did send something.
    assert message is not None
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "failed"
    assert attachment.provider_url == MEDIA_URL
    assert any("media.ingest_failed" in r.message for r in caplog.records)


async def test_storage_write_failure_does_not_cost_the_message(db, tenant_ctx, caplog):
    """The critical case: `store()` raises something that is neither a
    ValidationError nor an httpx error (a boto3/botocore ClientError).

    Before the fix that exception escaped `ingest_inbound_media` and rolled
    back `add_message`, so a bonus attachment destroyed the customer's
    message. The message must survive; the failure must be recorded and loud.
    """
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(
        store_error=StorageClientError("AccessDenied: not authorized to PutObject")
    )

    with caplog.at_level(logging.ERROR):
        message = await _inbound(db, tenant_id, conversation, storage)

    assert message is not None  # not raised — the message is durable
    assert storage.fetch_calls == 1
    assert storage.store_calls == 1
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "failed"
    assert attachment.processing_status == "failed"
    assert attachment.provider_url == MEDIA_URL
    assert any("media.ingest_failed" in r.message for r in caplog.records)


async def test_an_unexpected_error_class_is_also_contained(db, tenant_ctx, caplog):
    """No media failure class may escape — including ones we never modelled."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(error=RuntimeError("thread pool exploded"))

    with caplog.at_level(logging.ERROR):
        message = await _inbound(db, tenant_id, conversation, storage)

    assert message is not None
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "failed"
    assert any("media.ingest_failed" in r.message for r in caplog.records)


async def test_undurable_passthrough_is_recorded_as_failed(db, tenant_ctx, caplog):
    """No S3 configured: keeping only the expiring URL must not look like success."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    storage = FakeStorage(durable=False)

    with caplog.at_level(logging.ERROR):
        message = await _inbound(db, tenant_id, conversation, storage)

    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "failed"
    assert attachment.storage_key is None
    assert any("media.not_durable" in r.message for r in caplog.records)


async def test_a_failed_attachment_is_retried_on_redelivery(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    broken = FakeStorage(error=httpx.ConnectError("transient"))
    _set_scanner(monkeypatch)  # pin the unconfigured default for determinism

    message = await _inbound(db, tenant_id, conversation, broken)
    failed = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert failed.scan_status == "failed"

    healthy = FakeStorage()
    retried = await MediaService.ingest_inbound_media(
        db, tenant_id, message=message, media_url=MEDIA_URL, storage=healthy
    )

    assert retried is not None
    assert retried.scan_status == "pending"  # no scanner configured: not re-scanned
    assert healthy.fetch_calls == 1
    # The failed row is reused, not duplicated.
    assert len(await MediaService.list_for_message(db, tenant_id, message.id)) == 1


# ------------------------------------------------- scanner (clamd INSTREAM) ---


async def test_the_clamd_protocol_parses_a_clean_verdict() -> None:
    daemon = await FakeClamd(reply="stream: OK\n").start()
    try:
        result = await scan_bytes(PAYLOAD, host=daemon.host, port=daemon.port)
    finally:
        await daemon.stop()
    assert result.status == "clean"
    assert result.signature is None
    # The client sent the object as one INSTREAM stream of length-prefixed
    # chunks — what the daemon actually received is pinned.
    assert daemon.last_stream == PAYLOAD


async def test_the_clamd_protocol_parses_an_infected_verdict_with_its_signature() -> None:
    daemon = await FakeClamd(reply="stream: Eicar-Test-Signature FOUND\n").start()
    try:
        result = await scan_bytes(PAYLOAD, host=daemon.host, port=daemon.port)
    finally:
        await daemon.stop()
    assert result.status == "infected"
    assert result.signature == "Eicar-Test-Signature"


async def test_the_clamd_protocol_refuses_a_malformed_reply() -> None:
    """An unreadable reply is NO verdict — never accidentally clean."""
    daemon = await FakeClamd(reply="INSTREAM size limit exceeded. ERROR\n").start()
    try:
        with pytest.raises(MediaScannerError):
            await scan_bytes(PAYLOAD, host=daemon.host, port=daemon.port)
    finally:
        await daemon.stop()


async def test_the_clamd_protocol_refuses_a_dead_daemon() -> None:
    """The socket shape of a down daemon (accept, close) is an error."""
    daemon = await FakeClamd(refuse=True).start()
    try:
        with pytest.raises(MediaScannerError):
            await scan_bytes(PAYLOAD, host=daemon.host, port=daemon.port)
    finally:
        await daemon.stop()


async def test_the_clamd_protocol_refuses_an_unreachable_host() -> None:
    """Nothing listens on the ephemeral port after the server stops."""
    daemon = await FakeClamd().start()
    port = daemon.port
    await daemon.stop()
    with pytest.raises(MediaScannerError):
        await scan_bytes(PAYLOAD, host="127.0.0.1", port=port)


async def test_a_clean_scan_advances_the_image_to_scanned(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    daemon = await FakeClamd(reply="stream: OK\n").start()
    try:
        _set_scanner(monkeypatch, host=daemon.host, port=daemon.port)
        message = await _inbound(db, tenant_id, conversation, FakeStorage())
    finally:
        await daemon.stop()

    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "scanned"
    assert daemon.streams_seen == 1
    assert daemon.last_stream == PAYLOAD
    # A clean scan says nothing about processing: that gap stays with the
    # deferred worker (ADR-062).
    assert attachment.processing_status == "pending"


async def test_an_infected_image_is_quarantined_and_never_scanned(
    db, tenant_ctx, monkeypatch, caplog
):
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    daemon = await FakeClamd(reply="stream: Eicar-Test-Signature FOUND\n").start()
    try:
        _set_scanner(monkeypatch, host=daemon.host, port=daemon.port)
        with caplog.at_level(logging.ERROR):
            message = await _inbound(db, tenant_id, conversation, FakeStorage())
    finally:
        await daemon.stop()

    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "quarantined"
    # The message still survived — quarantine refuses the IMAGE, not the chat.
    assert message is not None
    assert any("media.quarantined" in r.message for r in caplog.records)
    assert any("Eicar-Test-Signature" in r.getMessage() for r in caplog.records)


async def test_a_scanner_outage_leaves_the_image_pending_and_the_message_alive(
    db, tenant_ctx, monkeypatch, caplog
):
    """ADR-062: a scanner problem is "not yet scanned", never a false clean."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    daemon = await FakeClamd(refuse=True).start()
    try:
        _set_scanner(monkeypatch, host=daemon.host, port=daemon.port)
        with caplog.at_level(logging.WARNING):
            message = await _inbound(db, tenant_id, conversation, FakeStorage())
    finally:
        await daemon.stop()

    # The message flow survived the scanner being down.
    assert message is not None
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "pending"
    assert attachment.storage_key == "media/abc.jpg"  # the bytes ARE durable
    assert any("media.scan_unavailable" in r.message for r in caplog.records)


async def test_a_pending_scan_is_retried_once_a_scanner_is_configured(db, tenant_ctx, monkeypatch):
    """The pending state is retryable BY a configured scanner, and only then.

    First ingest with no scanner: the row stays pending and a re-entry must
    not burn the (soon-expiring) provider URL. Once a scanner exists, the
    same re-entry retries fetch + scan together and the row completes.
    """
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    message = await _inbound(db, tenant_id, conversation, FakeStorage())
    first = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert first.scan_status == "pending"

    idle = FakeStorage()
    again = await MediaService.ingest_inbound_media(
        db, tenant_id, message=message, media_url=MEDIA_URL, storage=idle
    )
    assert again.scan_status == "pending"
    assert idle.fetch_calls == 0  # unconfigured: nothing to retry

    daemon = await FakeClamd(reply="stream: OK\n").start()
    try:
        _set_scanner(monkeypatch, host=daemon.host, port=daemon.port)
        retried_storage = FakeStorage()
        retried = await MediaService.ingest_inbound_media(
            db, tenant_id, message=message, media_url=MEDIA_URL, storage=retried_storage
        )
    finally:
        await daemon.stop()

    assert retried is not None
    assert retried.scan_status == "scanned"
    assert retried_storage.fetch_calls == 1
    assert daemon.streams_seen == 1
    assert len(await MediaService.list_for_message(db, tenant_id, message.id)) == 1


async def test_non_image_media_keeps_the_stored_mark(db, tenant_ctx, monkeypatch):
    """The scan gates IMAGE egress (ADR-062); other media is untouched."""
    tenant_id = tenant_ctx.tenant_id
    conversation = await _conversation(db, tenant_id)
    _set_scanner(monkeypatch)  # unconfigured — irrelevant to the stored mark

    message = await _inbound(
        db, tenant_id, conversation, FakeStorage(content_type="application/pdf")
    )

    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.mime_type == "application/pdf"
    assert attachment.scan_status == "stored"
    assert attachment.processing_status == "pending"
