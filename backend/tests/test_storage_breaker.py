"""WS-A3 — object-storage calls are routed through the `storage.objects` breaker.

`CircuitBreaker` was complete, unit-tested and imported by nothing, so the
storage port had no back-pressure at all: every ingest kept calling a dead
provider. These tests pin the two call sites to the SHARED breaker and — the
part that actually matters — that an OPEN breaker is contained by the media
pipeline instead of costing the customer's inbound message.

DB-free tests cover the wiring; the message-survival test needs a real database
and skips locally (it runs in CI), like the rest of the media-pipeline suite.
"""

from __future__ import annotations

import logging
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.storage as storage_mod
from app.core.circuit_breaker import STORAGE_OBJECTS, get_breaker, reset_breakers
from app.core.errors import CircuitOpenError
from app.core.storage import FetchedMedia, ObjectStorage
from app.modules.conversations.media import MediaService
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService

MEDIA_URL = "https://cdn.example.test/photo.jpg"
PAYLOAD = b"\xff\xd8\xff\xe0not-really-a-jpeg"


@pytest.fixture(autouse=True)
def _fresh_breakers():
    """The registry is process-wide, so one case must not leak state into the next."""
    reset_breakers()
    yield
    reset_breakers()


async def _provider_down() -> None:
    raise RuntimeError("storage provider down")


async def _open_storage_breaker() -> None:
    """Trip the shared breaker with a threshold of 1 and assert it is OPEN."""
    breaker = get_breaker(STORAGE_OBJECTS, failure_threshold=1)
    with pytest.raises(RuntimeError):
        await breaker.call(_provider_down)
    assert breaker.is_open


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Point the port's own AsyncClient at a MockTransport (see test_media_pipeline)."""
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(storage_mod.httpx, "AsyncClient", factory)


def _configured_port() -> ObjectStorage:
    port = ObjectStorage()
    # HERMETIC by force: ObjectStorage() reads the ambient settings, and this
    # repo's real .env carries a live Supabase project — an un-overridden
    # attribute here meant the "failing put" test fired REAL HTTP at the
    # PRODUCTION storage bucket. Pin the whole attribute surface and the S3
    # branch explicitly so the test can only ever talk to its own mock.
    port._bucket = "bucket"
    port._endpoint = "https://s3.test"
    port._region = "us-east-1"
    port._key = "key"
    port._secret = "secret"
    port._supabase_url = ""
    port._supabase_key = ""
    port._rest_client = None
    port._signed_url_cache = {}
    assert port.configured
    return port


class _RecordingS3:
    """Stands in for the boto3 client; records whether put_object was entered."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.error = error

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {}


async def test_fetch_is_refused_while_the_storage_breaker_is_open(monkeypatch) -> None:
    contacted = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        contacted["n"] += 1
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=PAYLOAD)

    monkeypatch.setattr(storage_mod, "assert_public_url", lambda url: url)
    _patch_httpx(monkeypatch, handler)
    await _open_storage_breaker()

    with pytest.raises(CircuitOpenError):
        await ObjectStorage().fetch(MEDIA_URL, max_bytes=1024)

    assert contacted["n"] == 0  # the provider was never contacted


async def test_store_is_refused_while_the_storage_breaker_is_open(monkeypatch) -> None:
    """The SYNC boto3 call is routed through the breaker, not around it."""
    port = _configured_port()
    s3 = _RecordingS3()
    monkeypatch.setattr(port, "_s3", lambda: s3)
    await _open_storage_breaker()

    media = FetchedMedia(data=PAYLOAD, content_type="image/jpeg", checksum="deadbeef")
    with pytest.raises(CircuitOpenError):
        await port.store(media)

    assert s3.calls == []  # boto3 was never entered


async def test_a_failing_put_object_trips_the_storage_breaker(monkeypatch) -> None:
    """Failures out of the thread-pool hop are accounted against the breaker."""
    breaker = get_breaker(STORAGE_OBJECTS, failure_threshold=2)
    port = _configured_port()
    s3 = _RecordingS3(error=RuntimeError("AccessDenied"))
    monkeypatch.setattr(port, "_s3", lambda: s3)

    media = FetchedMedia(data=PAYLOAD, content_type="image/jpeg", checksum="deadbeef")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await port.store(media)

    assert len(s3.calls) == 2
    assert breaker.is_open


# ------------------------------------------------------------- DB-backed ---


async def test_inbound_message_survives_an_open_storage_breaker(
    db: AsyncSession, tenant_ctx, caplog
) -> None:
    """The past bug in this area: a storage failure rolled back `add_message`.

    With the breaker OPEN, `ObjectStorage.fetch` raises `CircuitOpenError`
    instead of downloading. That must stay contained by
    `MediaService.ingest_inbound_media` — the attachment is recorded failed and
    the customer's message is still durable.
    """
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Breaker Tester"
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )

    await _open_storage_breaker()

    # The real port, deliberately: it is `fetch` that raises while open.
    port = ObjectStorage()
    with caplog.at_level(logging.ERROR):
        message = await ConversationService.add_message(
            db,
            tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            sender_type="customer",
            media_url=MEDIA_URL,
            media_type="image",
            channel_message_id=f"wamid-{uuid.uuid4().hex[:12]}",
            media_storage=port,
        )

    assert message is not None  # not raised — the message is durable
    attachment = (await MediaService.list_for_message(db, tenant_id, message.id))[0]
    assert attachment.scan_status == "failed"
    assert attachment.provider_url == MEDIA_URL
    assert any("media.ingest_failed" in r.message for r in caplog.records)
