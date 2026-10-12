"""ADR-062 closure — the rescan sweep for scanner-orphaned images.

The ingest scan runs on in-memory bytes before the turn; when clamd is
unreachable (or not yet deployed) the attachment row stays ``pending`` and
NOTHING ever revisited it — the vision gate refuses pending, so the image was
invisible to the customer agent forever. The sweep re-reads the durable object
and reuses the exact ingest verdict path; these pins hold it to that contract.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.core.media_scanner import MediaScannerError
from app.modules.conversations import media as media_mod
from app.modules.conversations.media import MediaService
from app.modules.conversations.models import Attachment
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer


class _FakeStorage:
    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs
        self.read_keys: list[str] = []

    async def read_object(self, key: str, *, max_bytes=None):
        self.read_keys.append(key)
        if key not in self.blobs:
            raise RuntimeError("object not found")
        return SimpleNamespace(data=self.blobs[key])


def _settings(configured: bool):
    return SimpleNamespace(
        media_scanner_host="clamd" if configured else "",
        media_scanner_port=3310 if configured else 0,
        media_scanner_configured=configured,
    )


async def _seed_pending_image(db, tenant_id, *, status: str = "pending") -> Attachment:
    customer = Customer(tenant_id=tenant_id, name=f"Rescan {uuid.uuid4().hex[:6]}")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="photo",
    )
    await db.flush()
    attachment = Attachment(
        tenant_id=tenant_id,
        message_id=message.id,
        conversation_id=conversation.id,
        storage_key=f"media/{uuid.uuid4().hex}.png",
        mime_type="image/png",
        size=10,
        scan_status=status,
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def _attachment(db, tenant_id, attachment_id) -> Attachment:
    return (
        await db.execute(
            select(Attachment).where(
                Attachment.tenant_id == tenant_id, Attachment.id == attachment_id
            )
        )
    ).scalar_one()


async def test_a_pending_image_gets_its_verdict_and_flips_to_scanned(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    attachment = await _seed_pending_image(db, tenant_id)
    storage = _FakeStorage({attachment.storage_key: b"png-bytes"})

    monkeypatch.setattr(media_mod, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(media_mod, "get_storage", lambda: storage)

    async def clean(data, *, host, port):
        return SimpleNamespace(status="clean", signature=None)

    monkeypatch.setattr(media_mod.media_scanner, "scan", clean)

    scanned = await MediaService.rescan_pending_images(db, tenant_id)

    assert scanned == 1
    refreshed = await _attachment(db, tenant_id, attachment.id)
    assert refreshed.scan_status == "scanned"
    assert storage.read_keys == [attachment.storage_key], (
        "the sweep must re-read the durable object, never the provider URL"
    )


async def test_without_a_scanner_the_sweep_is_a_noop(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    attachment = await _seed_pending_image(db, tenant_id)
    storage = _FakeStorage({attachment.storage_key: b"png-bytes"})

    monkeypatch.setattr(media_mod, "get_settings", lambda: _settings(False))
    monkeypatch.setattr(media_mod, "get_storage", lambda: storage)

    assert await MediaService.rescan_pending_images(db, tenant_id) == 0
    assert storage.read_keys == [], "no scanner means no fetch, not a failed scan"
    refreshed = await _attachment(db, tenant_id, attachment.id)
    assert refreshed.scan_status == "pending"


async def test_a_scanner_outage_leaves_the_row_pending(db, tenant_ctx, monkeypatch):
    """Fail-closed: an unreachable clamd widens nothing. The row stays exactly
    as the gate sees it — pending — and the sweep reports the attempt."""
    tenant_id = tenant_ctx.tenant_id
    attachment = await _seed_pending_image(db, tenant_id)
    storage = _FakeStorage({attachment.storage_key: b"png-bytes"})

    monkeypatch.setattr(media_mod, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(media_mod, "get_storage", lambda: storage)

    async def down(data, *, host, port):
        raise MediaScannerError("clamd unreachable")

    monkeypatch.setattr(media_mod.media_scanner, "scan", down)

    assert await MediaService.rescan_pending_images(db, tenant_id) == 1
    refreshed = await _attachment(db, tenant_id, attachment.id)
    assert refreshed.scan_status == "pending"


async def test_an_infected_image_is_quarantined_by_the_sweep(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    attachment = await _seed_pending_image(db, tenant_id)
    storage = _FakeStorage({attachment.storage_key: b"evil"})

    monkeypatch.setattr(media_mod, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(media_mod, "get_storage", lambda: storage)

    async def infected(data, *, host, port):
        return SimpleNamespace(status="infected", signature="Eicar-Test-File")

    monkeypatch.setattr(media_mod.media_scanner, "scan", infected)

    await MediaService.rescan_pending_images(db, tenant_id)
    refreshed = await _attachment(db, tenant_id, attachment.id)
    assert refreshed.scan_status == "quarantined"


async def test_the_sweep_only_touches_pending_images(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    scanned = await _seed_pending_image(db, tenant_id, status="scanned")
    quarantined = await _seed_pending_image(db, tenant_id, status="quarantined")
    pending = await _seed_pending_image(db, tenant_id)
    storage = _FakeStorage({pending.storage_key: b"png-bytes"})

    monkeypatch.setattr(media_mod, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(media_mod, "get_storage", lambda: storage)

    async def clean(data, *, host, port):
        return SimpleNamespace(status="clean", signature=None)

    monkeypatch.setattr(media_mod.media_scanner, "scan", clean)

    assert await MediaService.rescan_pending_images(db, tenant_id) == 1
    assert storage.read_keys == [pending.storage_key], (
        "scanned and quarantined rows carry a final verdict — re-scanning them "
        "could only ever reopen a decision"
    )
    assert (await _attachment(db, tenant_id, scanned.id)).scan_status == "scanned"
    assert (await _attachment(db, tenant_id, quarantined.id)).scan_status == "quarantined"


async def test_the_scheduler_wires_the_sweep_per_tenant():
    """The producer must exist: a handler nobody schedules is this repo's
    named failure mode. The job rides the durable per-tenant recurring
    registry — hourly, seeded for every active tenant at boot."""
    from app.workers.scheduler_worker import _HANDLERS, RECURRING_JOBS

    assert "media.rescan_pending_images" in RECURRING_JOBS
    assert _HANDLERS["media.rescan_pending_images"] is not None
